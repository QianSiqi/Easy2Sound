// HN-SEP：呼吸/发声分离 + 张力滤波
// 与 util/hnsep_onnx_infer.py 对齐：
// - predict_fromaudio：STFT → ONNX mask 推理 → ISTFT
// - pre_emphasis_base_tension：频域线性增益滤波
// 复数频谱布局统一为列主序 [bin][frame]（bin 外层，与 numpy C 顺序一致）
use std::collections::HashMap;
use std::sync::{Arc, Mutex};

use rustfft::num_complex::Complex;
use rustfft::FftPlanner;

pub struct HnsepModel<'a> {
    session: &'a Arc<Mutex<ort::session::Session>>,
    n_fft: usize,
    hop_length: usize,
    sr: usize,
    seg_length: usize,
    window: Vec<f32>, // hann sym=False
}

impl<'a> HnsepModel<'a> {
    pub fn new(session: &'a Arc<Mutex<ort::session::Session>>, n_fft: usize, hop_length: usize, sr: usize) -> Self {
        let seg_length = 32 * hop_length;
        // torch/signal.windows.hann(sym=False)：周期窗
        let window: Vec<f32> = (0..n_fft)
            .map(|k| 0.5 * (1.0 - (2.0 * std::f32::consts::PI * k as f32 / n_fft as f32).cos()))
            .collect();
        HnsepModel { session, n_fft, hop_length, sr, seg_length, window }
    }

    /// torch 风格 STFT（center=True reflect pad n_fft/2，hann sym=False，rfft 无归一化）
    /// 返回 (spec 列主序 [bin][frame], n_frames)
    fn stft(&self, x: &[f32]) -> (Vec<Complex<f32>>, usize) {
        let n = self.n_fft;
        let hop = self.hop_length;
        let pad = n / 2;
        let mut xp = Vec::with_capacity(x.len() + 2 * pad);
        for i in (0..pad).rev() {
            xp.push(x[i.min(x.len() - 1)]);
        }
        xp.extend_from_slice(x);
        for i in 0..pad {
            let idx = x.len().saturating_sub(2).saturating_sub(i);
            xp.push(x[idx]);
        }
        let n_frames = 1 + (xp.len() - n) / hop;
        let n_bins = n / 2 + 1;
        let mut spec = vec![Complex::new(0f32, 0f32); n_bins * n_frames];
        let mut planner = FftPlanner::<f32>::new();
        let fft = planner.plan_fft_forward(n);
        let mut buf = vec![Complex::new(0f32, 0f32); n];
        for f in 0..n_frames {
            let start = f * hop;
            for k in 0..n {
                buf[k] = Complex::new(xp[start + k] * self.window[k], 0.0);
            }
            fft.process(&mut buf);
            for k in 0..n_bins {
                spec[k * n_frames + f] = buf[k];
            }
        }
        (spec, n_frames)
    }

    /// overlap-add ISTFT（win² 归一化，trim n_fft/2），与 torch/numpy 版一致
    fn istft(&self, spec: &[Complex<f32>], n_frames: usize) -> Vec<f32> {
        let n = self.n_fft;
        let hop = self.hop_length;
        let n_bins = n / 2 + 1;
        let output_len = n + (n_frames - 1) * hop;
        let mut output = vec![0f64; output_len];
        let mut win_sum = vec![0f64; output_len];
        let mut planner = FftPlanner::<f32>::new();
        let ifft = planner.plan_fft_inverse(n);
        let mut buf = vec![Complex::new(0f32, 0f32); n];
        for f in 0..n_frames {
            let start = f * hop;
            for k in 0..n_bins {
                buf[k] = spec[k * n_frames + f];
            }
            for k in n_bins..n {
                buf[k] = buf[n - k].conj();
            }
            ifft.process(&mut buf);
            for k in 0..n {
                // numpy irfft 自带 1/n 归一化，rustfft 逆变换没有，需手动除
                let v = buf[k].re / n as f32;
                output[start + k] += v as f64 * self.window[k] as f64;
                win_sum[start + k] += (self.window[k] as f64) * (self.window[k] as f64);
            }
        }
        let pad = n / 2;
        let out: Vec<f32> = (0..output_len)
            .map(|i| {
                if win_sum[i] < 1e-8 { 0.0 } else { (output[i] / win_sum[i]) as f32 }
            })
            .collect();
        if out.len() > 2 * pad {
            out[pad..out.len() - pad].to_vec()
        } else {
            out
        }
    }

    /// wave: [T] → 分离后的波形 [T]（与 CascadedNet.predict_fromaudio 对齐）
    pub fn predict_fromaudio(&self, wave: &[f32]) -> Result<Vec<f32>, String> {
        let t = wave.len();
        let hop = self.hop_length;
        let t1 = t + hop;
        let seg = self.seg_length;
        let t_pad = seg * ((t1 - 1) / seg + 1) - t1;
        let nl_pad = t_pad / 2 / hop;
        let tl_pad = nl_pad * hop;
        let tr_pad = t_pad - tl_pad;

        let mut x_padded = vec![0f32; tl_pad];
        x_padded.extend_from_slice(wave);
        x_padded.resize(tl_pad + t + tr_pad, 0f32);

        let (spec, n_frames) = self.stft(&x_padded);
        let n_bins = self.n_fft / 2 + 1;
        let n_elem = n_bins * n_frames;

        // 输入 [1, 2, n_bins, n_frames]
        let mut input_flat = Vec::with_capacity(2 * n_elem);
        for b in 0..n_bins {
            for f in 0..n_frames {
                input_flat.push(spec[b * n_frames + f].re);
            }
        }
        for b in 0..n_bins {
            for f in 0..n_frames {
                input_flat.push(spec[b * n_frames + f].im);
            }
        }
        let mut inputs: HashMap<&str, ort::value::DynTensor> = HashMap::new();
        inputs.insert(
            "input",
            ort::value::Tensor::from_array((vec![1i64, 2, n_bins as i64, n_frames as i64], input_flat))
                .map_err(|e| e.to_string())?
                .upcast(),
        );
        let mut session = self.session.lock().map_err(|_| "hnsep session lock poisoned")?;
        let outputs = session.run(inputs).map_err(|e| e.to_string())?;
        let (_shape, mask) = outputs[0].try_extract_tensor::<f32>().map_err(|e| e.to_string())?;

        // spec * mask（复数）
        let mut spec_pred = spec;
        for b in 0..n_bins {
            for f in 0..n_frames {
                let mr = mask[b * n_frames + f];
                let mi = mask[n_elem + b * n_frames + f];
                spec_pred[b * n_frames + f] *= Complex::new(mr, mi);
            }
        }
        let x_pred = self.istft(&spec_pred, n_frames);
        Ok(x_pred[tl_pad..tl_pad + t].to_vec())
    }

    /// 频域张力滤波（与 pre_emphasis_base_tension 对齐）：wave: [T], b: 张力参数
    pub fn pre_emphasis_base_tension(&self, wave: &[f32], b: f32) -> Vec<f32> {
        let original_length = wave.len();
        let hop = self.hop_length;
        let n = self.n_fft;
        let n_bins = n / 2 + 1;

        let pad_length = (hop - (original_length % hop)) % hop;
        let mut wave_padded = wave.to_vec();
        wave_padded.resize(original_length + pad_length, 0f32);

        let (spec, n_frames) = self.stft(&wave_padded);
        let n_elem = n_bins * n_frames;

        // log 幅度 + 频域线性增益
        let x0 = n_bins as f32 / ((self.sr as f32 / 2.0) / 1500.0);
        let freq_filter: Vec<f32> = (0..n_bins)
            .map(|k| ((-b / x0) * k as f32 + b).clamp(-2.0, 2.0))
            .collect();

        let mut spec_filtered = vec![Complex::new(0f32, 0f32); n_elem];
        for b in 0..n_bins {
            for f in 0..n_frames {
                let c = spec[b * n_frames + f];
                let amp = c.norm().max(1e-9).ln() + freq_filter[b];
                let amp = amp.exp();
                spec_filtered[b * n_frames + f] = Complex::new(amp * c.re / c.norm().max(1e-12),
                                                               amp * c.im / c.norm().max(1e-12));
            }
        }
        let mut filtered = self.istft(&spec_filtered, n_frames);

        // 峰值缩放（与 python 一致）
        let original_max = wave.iter().fold(0f32, |a, &v| a.max(v.abs()));
        let filtered_max = filtered.iter().fold(0f32, |a, &v| a.max(v.abs()));
        if filtered_max > 0.0 {
            let scale = original_max / filtered_max * ((b / -15.0).clamp(0.0, 0.33) + 1.0);
            for v in filtered.iter_mut() {
                *v *= scale;
            }
        }
        filtered.truncate(original_length);
        filtered
    }
}
