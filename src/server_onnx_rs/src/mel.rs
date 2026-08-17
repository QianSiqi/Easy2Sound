// mel 频谱分析：与 util/wav2mel_numpy.py 对齐
// - STFT：torch 风格（reflect pad + hann sym 窗 + 无归一化 rfft）
// - mel 滤波器组：复刻 librosa.filters.mel（slaney 刻度, norm='slaney'）
// - key_shift：变 n_fft/win 长度后截断/补零 + 幅度缩放
use rustfft::num_complex::Complex;
use rustfft::FftPlanner;

pub struct MelAnalysis {
    pub sample_rate: usize,
    pub n_fft: usize,
    pub win_size: usize,
    pub hop_length: usize,
    pub f_min: f32,
    pub f_max: f32,
    pub n_mels: usize,
    pub(crate) mel_basis: Vec<Vec<f32>>, // [n_mels][n_fft/2+1]
}

// ---- librosa slaney 刻度（librosa 0.11 mel_frequencies：
//      mel 域等距 linspace(hz_to_mel(fmin), hz_to_mel(fmax)) 再转回 Hz；
//      对数区 logstep = ln(6.4)/27 —— Slaney 原版常数，不是 ln(2)/27） ----
fn hz_to_mel_slaney(f: f32) -> f32 {
    let f_sp = 200.0 / 3.0;
    let min_log_hz = 1000.0;
    let min_log_mel = min_log_hz / f_sp; // f_min = 0
    let logstep = (6.4f32).ln() / 27.0;
    let mels = f / f_sp;
    if f >= min_log_hz {
        min_log_mel + (f / min_log_hz).ln() / logstep
    } else {
        mels
    }
}

fn mel_to_hz_slaney(m: f32) -> f32 {
    let f_sp = 200.0 / 3.0;
    let min_log_hz = 1000.0;
    let min_log_mel = min_log_hz / f_sp;
    let logstep = (6.4f32).ln() / 27.0;
    let freqs = f_sp * m;
    if m >= min_log_mel {
        min_log_hz * (logstep * (m - min_log_mel)).exp()
    } else {
        freqs
    }
}

fn mel_frequencies(n: usize, fmin: f32, fmax: f32) -> Vec<f32> {
    let min_mel = hz_to_mel_slaney(fmin);
    let max_mel = hz_to_mel_slaney(fmax);
    (0..n)
        .map(|i| {
            let m = min_mel + (max_mel - min_mel) * i as f32 / (n - 1) as f32;
            mel_to_hz_slaney(m)
        })
        .collect()
}

fn build_mel_basis(sr: usize, n_fft: usize, n_mels: usize, fmin: f32, fmax: f32) -> Vec<Vec<f32>> {
    let n_freqs = n_fft / 2 + 1;
    // librosa fft_frequencies
    let fft_freqs: Vec<f32> = (0..n_freqs).map(|i| i as f32 * sr as f32 / n_fft as f32).collect();
    let hz_points = mel_frequencies(n_mels + 2, fmin, fmax);

    // 三角滤波器（librosa: max(0, min(lower, upper))）
    let mut fb = vec![vec![0f32; n_freqs]; n_mels];
    let fdiff: Vec<f32> = hz_points.windows(2).map(|w| w[1] - w[0]).collect();
    for i in 0..n_mels {
        for (j, &f) in fft_freqs.iter().enumerate() {
            let lower = -(hz_points[i] - f) / fdiff[i];
            let upper = (hz_points[i + 2] - f) / fdiff[i + 1];
            fb[i][j] = lower.min(upper).max(0.0);
        }
        // norm='slaney'：权重 × 2/(right-left) 使滤波器面积为 1
        let area = 2.0 / (hz_points[i + 2] - hz_points[i]);
        for v in fb[i].iter_mut() {
            *v *= area;
        }
    }
    fb
}

impl MelAnalysis {
    pub fn new(sample_rate: usize, n_fft: usize, win_size: usize, hop_length: usize,
               f_min: f32, f_max: f32, n_mels: usize) -> Self {
        let mel_basis = build_mel_basis(sample_rate, n_fft, n_mels, f_min, f_max);
        MelAnalysis { sample_rate, n_fft, win_size, hop_length, f_min, f_max, n_mels, mel_basis }
    }

    /// y: [T]，key_shift 半音，speed 帧率缩放 → mel [n_mels][n_frames]
    pub fn call(&self, y: &[f32], key_shift: f32, speed: f32) -> Vec<Vec<f32>> {
        let factor = 2f32.powf(key_shift / 12.0);
        let win_size_new = (self.win_size as f32 * factor).round() as usize;
        let hop = (self.hop_length as f32 * speed).round() as usize;

        // torch hann_window(sym=True)
        let n_win = win_size_new.max(2);
        let window: Vec<f32> = (0..n_win)
            .map(|k| 0.5 * (1.0 - (2.0 * std::f32::consts::PI * k as f32 / (n_win - 1) as f32).cos()))
            .collect();

        // reflect padding（numpy/torch mode='reflect'）
        let pad_left = (win_size_new - hop) / 2;
        let pad_right = (win_size_new - hop + 1) / 2;
        let mut x = Vec::with_capacity(y.len() + pad_left + pad_right);
        // numpy reflect：边缘元素不重复，[a,b,c] pad 2 → [b,a,b,c,b]
        for i in (0..pad_left).rev() {
            x.push(y[i.min(y.len() - 1)]);
        }
        x.extend_from_slice(y);
        for i in 0..pad_right {
            let idx = y.len().saturating_sub(2).saturating_sub(i);
            x.push(y[idx]);
        }

        let n_frames = 1 + (x.len() - n_win) / hop;
        let mut spec = vec![vec![0f32; n_frames]; n_win / 2 + 1];

        let mut planner = FftPlanner::<f32>::new();
        let fft = planner.plan_fft_forward(n_win);
        let mut buf: Vec<Complex<f32>> = vec![Complex::new(0.0, 0.0); n_win];
        let mut frame_in: Vec<Complex<f32>> = vec![Complex::new(0.0, 0.0); n_win];

        for f in 0..n_frames {
            let start = f * hop;
            for k in 0..n_win {
                frame_in[k] = Complex::new(x[start + k] * window[k], 0.0);
            }
            buf.copy_from_slice(&frame_in);
            fft.process(&mut buf);
            for k in 0..(n_win / 2 + 1) {
                spec[k][f] = buf[k].norm();
            }
        }

        // key_shift 补偿：截断或补零到标准 n_fft//2+1
        let size = self.n_fft / 2 + 1;
        let spec_rows = spec.len();
        let scale = self.win_size as f32 / win_size_new as f32;
        let mut spec_out: Vec<Vec<f32>>;
        if key_shift != 0.0 {
            if spec_rows < size {
                spec_out = spec.clone();
                spec_out.resize(size, vec![0f32; n_frames]);
            } else {
                spec_out = spec;
            }
            spec_out.truncate(size);
            for row in spec_out.iter_mut() {
                for v in row.iter_mut() {
                    *v *= scale;
                }
            }
        } else {
            spec_out = spec;
        }

        // mel 滤波: [n_mels][n_freqs] @ [n_freqs][n_frames]
        let mut mel_spec = vec![vec![0f32; n_frames]; self.n_mels];
        for m in 0..self.n_mels {
            for k in 0..size {
                let w = self.mel_basis[m][k];
                if w == 0.0 { continue; }
                for f in 0..n_frames {
                    mel_spec[m][f] += w * spec_out[k][f];
                }
            }
        }
        mel_spec
    }

    /// in-place: log(clip(x, 1e-9, inf))
    pub fn dynamic_range_compression(&self, x: &mut [f32]) {
        for v in x.iter_mut() {
            *v = (*v).max(1e-9).ln();
        }
    }
}
