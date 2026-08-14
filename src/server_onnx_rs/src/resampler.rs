// 核心渲染管线：与 server_onnx.py 的 Resampler 类对齐
// 主流程：读 wav → mel 分析 → 时间拉伸/插值 → pitch 曲线 → vocoder 推理 → 后处理
use std::collections::HashMap;
use std::path::Path;
use std::sync::{Arc, Mutex};

use crate::config::Config;
use crate::hnsep::HnsepModel;
use crate::mel::MelAnalysis;
use crate::pitch::{midi_to_hz, note_to_midi, pitch_string_to_cents};
use crate::wav::read_wav;

const FLAG_LIST: &[&str] = &["fe", "fl", "fo", "fv", "fp", "ve", "vo", "g", "t",
                              "A", "B", "G", "P", "S", "p", "R", "D", "C", "Z",
                              "Hv", "Hb", "Ht", "He"];

fn parse_flags(s: &str) -> HashMap<String, Option<i32>> {
    let s = s.replace('/', "");
    let bytes = s.as_bytes();
    let mut flags: HashMap<String, Option<i32>> = HashMap::new();
    let mut i = 0;
    while i < bytes.len() {
        let mut matched: Option<&str> = None;
        for name in FLAG_LIST {
            let n = name.as_bytes();
            if bytes.len() - i >= n.len() && &bytes[i..i + n.len()] == n {
                matched = Some(name);
                break;
            }
        }
        let Some(name) = matched else {
            i += 1;
            continue;
        };
        i += name.len();
        let mut val: Option<i32> = None;
        let start = i;
        while i < bytes.len() && (bytes[i].is_ascii_digit()
            || (i == start && (bytes[i] == b'+' || bytes[i] == b'-'))) {
            i += 1;
        }
        if i > start {
            val = s[start..i].parse().ok();
        }
        flags.insert(name.to_string(), val);
    }
    flags
}

// ---- 插值 ----

/// scipy interp1d(kind='linear')：x 严格递增，xq 在范围内
fn interp1d_linear(x: &[f32], y: &[f32], xq: &[f32]) -> Vec<f32> {
    xq.iter()
        .map(|&q| {
            if q <= x[0] { return y[0]; }
            if q >= x[x.len() - 1] { return *y.last().unwrap(); }
            let mut lo = 0usize;
            let mut hi = x.len() - 1;
            while hi - lo > 1 {
                let mid = (lo + hi) / 2;
                if x[mid] <= q { lo = mid; } else { hi = mid; }
            }
            let t = (q - x[lo]) / (x[hi] - x[lo]);
            y[lo] + (y[hi] - y[lo]) * t
        })
        .collect()
}

/// scipy Akima1DInterpolator（修正 Akima，端点斜率 = 端点段斜率，三次 Hermite 求值）
fn akima_interp1d(x: &[f32], y: &[f32], xq: &[f32]) -> Vec<f32> {
    let n = x.len();
    let mut d = vec![0f32; n - 1];
    for i in 0..n - 1 {
        d[i] = (y[i + 1] - y[i]) / (x[i + 1] - x[i]);
    }
    let mut m = vec![0f32; n];
    m[0] = d[0];
    m[n - 1] = d[n - 2];
    for i in 1..n - 1 {
        let denom = d[i - 1].abs() + d[i].abs();
        m[i] = if denom > 0.0 {
            (d[i] * d[i - 1].abs() + d[i - 1] * d[i].abs()) / denom
        } else {
            0.0
        };
    }
    xq.iter()
        .map(|&q| {
            if q <= x[0] { return y[0]; }
            if q >= x[n - 1] { return y[n - 1]; }
            let mut lo = 0usize;
            let mut hi = n - 1;
            while hi - lo > 1 {
                let mid = (lo + hi) / 2;
                if x[mid] <= q { lo = mid; } else { hi = mid; }
            }
            let h = x[hi] - x[lo];
            // scipy PPoly 约定：局部坐标 t = x - x[i]（系数已按 dx 归一化，不要除以 h）
            let t = q - x[lo];
            let c2 = (3.0 * d[lo] - 2.0 * m[lo] - m[hi]) / h;
            let c3 = (m[lo] + m[hi] - 2.0 * d[lo]) / (h * h);
            y[lo] + m[lo] * t + c2 * t * t + c3 * t * t * t
        })
        .collect()
}

/// numpy reflect pad 尾部索引（不重复边界元素，周期 2n-2）
fn reflect_tail_idx(k: usize, n: usize) -> usize {
    if n <= 1 { return 0; }
    let period = 2 * n - 2;
    let r = k % period;
    if r <= n - 2 { n - 2 - r } else { period - r }
}

pub struct Resampler<'a> {
    cfg: &'a Config,
    mel_analysis: &'a MelAnalysis,
    session: &'a Arc<Mutex<ort::session::Session>>,
    hnsep: Option<&'a HnsepModel<'a>>,
}

impl<'a> Resampler<'a> {
    pub fn new(cfg: &'a Config, mel_analysis: &'a MelAnalysis, session: &'a Arc<Mutex<ort::session::Session>>,
               hnsep: Option<&'a HnsepModel<'a>>) -> Self {
        Resampler { cfg, mel_analysis, session, hnsep }
    }

    pub fn render(&self, args: &RenderArgs) -> Result<Vec<f32>, String> {
        let t_render_start = std::time::Instant::now();
        let mut wave = read_wav(&args.in_file, self.cfg.sample_rate).map_err(|e| format!("read wav failed: {e}"))?;
        crate::log::info(&format!("read wav: {} samples ({:.2}s)", wave.len(), wave.len() as f32 / self.cfg.sample_rate as f32));
        let flags = parse_flags(&args.flags);

        // HN-SEP 呼吸/发声分离（Hb/Hv/Ht flags）
        let breath = flags.get("Hb").and_then(|v| *v).unwrap_or(100);
        let voicing = flags.get("Hv").and_then(|v| *v).unwrap_or(100);
        let tension = flags.get("Ht").and_then(|v| *v).unwrap_or(0);
        if breath != 100 || voicing != 100 || tension != 0 {
            crate::log::info(&format!("Hb={breath} Hv={voicing} Ht={tension}: running HN-SEP separation"));
            let hnsep = self.hnsep.ok_or("HN-SEP model not loaded (check hnsep_model_path)")?;
            let t_hnsep = std::time::Instant::now();
            let seg_output = hnsep.predict_fromaudio(&wave)?;
            crate::log::info(&format!("hnsep predict: {} samples in {:.3}s", seg_output.len(), t_hnsep.elapsed().as_secs_f32()));
            let breath_c = (breath.clamp(0, 500)) as f32 / 100.0;
            let voicing_c = (voicing.clamp(0, 150)) as f32 / 100.0;
            if tension != 0 {
                let tension_c = tension.clamp(-100, 100);
                let voicing_wave: Vec<f32> = seg_output.iter().map(|&v| voicing_c * v).collect();
                let tension_wave = hnsep.pre_emphasis_base_tension(&voicing_wave, -(tension_c as f32) / 50.0);
                wave = wave
                    .iter()
                    .zip(seg_output.iter())
                    .map(|(&w, &s)| breath_c * (w - s))
                    .zip(tension_wave.iter())
                    .map(|(a, &b)| a + b)
                    .collect();
            } else {
                wave = wave
                    .iter()
                    .zip(seg_output.iter())
                    .map(|(&w, &s)| breath_c * (w - s) + voicing_c * s)
                    .collect();
            }
        }

        // 峰值缩放
        let wave_max = wave.iter().fold(0f32, |a, &v| a.max(v.abs()));
        let scale: f32 = if wave_max >= 0.5 { 0.5 / wave_max } else { 1.0 };
        if scale != 1.0 {
            for v in wave.iter_mut() { *v *= scale; }
        }

        // mel 分析（gender flag 为半音偏移）
        let gender = flags.get("g").and_then(|v| *v).unwrap_or(0);
        let key_shift = gender as f32 / 100.0;
        let mut mel_origin = self.mel_analysis.call(&wave, key_shift, 1.0);
        for row in mel_origin.iter_mut() {
            self.mel_analysis.dynamic_range_compression(row);
        }
        let n_mels = mel_origin.len();
        crate::log::info(&format!("mel analysis: {n_mels}x{} (gender={gender})", mel_origin[0].len()));

        let thop_origin = self.cfg.origin_hop_size as f32 / self.cfg.sample_rate as f32;
        let thop = self.cfg.hop_size as f32 / self.cfg.sample_rate as f32;
        let t_origin = mel_origin[0].len();
        let mut t_area_origin: Vec<f32> = (0..t_origin).map(|i| i as f32 * thop_origin + thop_origin / 2.0).collect();
        let mut total_time = t_area_origin[t_origin - 1] + thop_origin / 2.0;

        let vel = 2f32.powf(1.0 - args.velocity / 100.0);
        let offset = args.offset / 1000.0;
        let cutoff = args.cutoff / 1000.0;
        let start = offset;
        let end = if args.cutoff < 0.0 { start - cutoff } else { total_time - cutoff };
        let con = start + args.consonant / 1000.0;

        let length_req = args.length as f32 / 1000.0;
        let mut stretch_length = end - con;

        // loop 模式（He flag 或全局 loop_mode）
        if self.cfg.loop_mode || flags.contains_key("He") {
            let mel_loop_start = ((con + thop_origin / 2.0) / thop_origin) as usize;
            let mel_loop_end = ((end + thop_origin / 2.0) / thop_origin) as usize;
            let pad_loop_size = (length_req / thop_origin) as usize + 1;
            let mut mel_new: Vec<Vec<f32>> = Vec::with_capacity(mel_origin.len());
            for row in &mel_origin {
                let loop_len = mel_loop_end.saturating_sub(mel_loop_start).min(row.len().saturating_sub(mel_loop_start));
                let mut r = row[..mel_loop_start].to_vec();
                for k in 0..pad_loop_size {
                    let src = if loop_len == 0 {
                        row.len().saturating_sub(1)
                    } else {
                        mel_loop_start + reflect_tail_idx(k, loop_len)
                    };
                    r.push(row[src]);
                }
                mel_new.push(r);
            }
            mel_origin = mel_new;
            stretch_length = pad_loop_size as f32 * thop_origin;
            t_area_origin = (0..mel_origin[0].len()).map(|i| i as f32 * thop_origin + thop_origin / 2.0).collect();
            total_time = t_area_origin[t_area_origin.len() - 1] + thop_origin / 2.0;
        }

        // 拉伸
        let scaling_ratio = if stretch_length < length_req { length_req / stretch_length } else { 1.0 };
        let stretch = |t: f32| if t < vel * con { t / vel } else { con + (t - vel * con) / scaling_ratio };

        let stretched_n_frames = ((con * vel + (total_time - con) * scaling_ratio) / thop) as usize + 1;
        let mut stretched_t_mel: Vec<f32> = (0..stretched_n_frames).map(|i| i as f32 * thop + thop / 2.0).collect();

        let start_left_mel_frames = ((start * vel + thop / 2.0) / thop) as usize;
        let cut_left_mel_frames = if start_left_mel_frames > self.cfg.fill { start_left_mel_frames - self.cfg.fill } else { 0 };
        let end_right_mel_frames = stretched_n_frames - ((length_req + con * vel + thop / 2.0) / thop) as usize;
        let cut_right_mel_frames = if end_right_mel_frames > self.cfg.fill { end_right_mel_frames - self.cfg.fill } else { 0 };

        if cut_right_mel_frames > 0 {
            stretched_t_mel.truncate(stretched_n_frames - cut_right_mel_frames);
        }
        if cut_left_mel_frames > 0 {
            if cut_left_mel_frames >= stretched_t_mel.len() {
                stretched_t_mel.clear();
            } else {
                stretched_t_mel.drain(..cut_left_mel_frames);
            }
        }

        if stretched_t_mel.is_empty() {
            return Err("render range empty (offset/length/velocity parameters invalid)".into());
        }

        let max_t = t_area_origin[t_area_origin.len() - 1];
        let stretch_t_mel: Vec<f32> = stretched_t_mel.iter().map(|&t| stretch(t).clamp(0.0, max_t)).collect();

        let new_start = start * vel - cut_left_mel_frames as f32 * thop;
        let new_end = length_req + con * vel - cut_left_mel_frames as f32 * thop;

        // mel 插值（每行）
        let t_render = stretch_t_mel.len();
        let mut mel_render: Vec<Vec<f32>> = Vec::with_capacity(n_mels);
        for row in &mel_origin {
            mel_render.push(interp1d_linear(&t_area_origin, row, &stretch_t_mel));
        }

        // pitch
        let t_mel: Vec<f32> = (0..t_render).map(|i| i as f32 * thop).collect();
        let mut pitch: Vec<f32> = args
            .pitchbend
            .iter()
            .map(|&c| c as f32 / 100.0 + args.pitch as f32)
            .collect();
        if let Some(t) = flags.get("t").and_then(|v| *v) {
            for p in pitch.iter_mut() { *p += t as f32 / 100.0; }
        }
        let t_pitch: Vec<f32> = (0..pitch.len()).map(|i| 60.0 * i as f32 / (args.tempo * 96.0) + new_start).collect();
        let t_clip: Vec<f32> = t_mel.iter().map(|&t| t.clamp(new_start, t_pitch[t_pitch.len() - 1])).collect();
        let pitch_render = akima_interp1d(&t_pitch, &pitch, &t_clip);
        let f0: Vec<f32> = pitch_render.iter().map(|&p| midi_to_hz(p)).collect();

        // ── vocoder 推理（mel: [1, T, n_mels] 列主序转置，f0: [1, T]） ──
        let mut mel_flat = Vec::with_capacity(n_mels * t_render);
        for i in 0..t_render {
            for m in 0..n_mels {
                mel_flat.push(mel_render[m][i]);
            }
        }
        let mut inputs: HashMap<&str, ort::value::DynTensor> = HashMap::new();
        inputs.insert(
            "mel",
            ort::value::Tensor::from_array((vec![1i64, t_render as i64, n_mels as i64], mel_flat))
                .map_err(|e| e.to_string())?
                .upcast(),
        );
        inputs.insert(
            "f0",
            ort::value::Tensor::from_array((vec![1i64, t_render as i64], f0)).map_err(|e| e.to_string())?.upcast(),
        );
        let mut session = self.session.lock().map_err(|_| "session lock poisoned")?;
        let t_infer = std::time::Instant::now();
        let outputs = session.run(inputs).map_err(|e| e.to_string())?;
        let (_shape, wav_con) = outputs[0].try_extract_tensor::<f32>().map_err(|e| e.to_string())?;
        crate::log::info(&format!(
            "vocoder infer: {t_render} frames -> {} samples in {:.3}s",
            wav_con.len(), t_infer.elapsed().as_secs_f32()
        ));

        // 切片
        let cut_l = (new_start * self.cfg.sample_rate as f32) as usize;
        let cut_r = (new_end * self.cfg.sample_rate as f32) as usize;
        let mut render: Vec<f32> = if cut_r <= wav_con.len() {
            wav_con[cut_l..cut_r].to_vec()
        } else {
            wav_con[cut_l..].to_vec()
        };

        // A flag：幅度调制（np.gradient 中心差分 + np.interp 线性插值）
        if let Some(a) = flags.get("A").and_then(|v| *v) {
            if a != 0 && pitch_render.len() > 1 && t_mel.len() > 1 {
                let a_clamped = (a as f32).clamp(-100.0, 100.0);
                let mut deriv = vec![0f32; pitch_render.len()];
                for i in 0..pitch_render.len() {
                    deriv[i] = if i == 0 {
                        (pitch_render[1] - pitch_render[0]) / (t_mel[1] - t_mel[0])
                    } else if i == pitch_render.len() - 1 {
                        (pitch_render[i] - pitch_render[i - 1]) / (t_mel[i] - t_mel[i - 1])
                    } else {
                        (pitch_render[i + 1] - pitch_render[i - 1]) / (t_mel[i + 1] - t_mel[i - 1])
                    };
                }
                let gain_at_mel: Vec<f32> = deriv.iter().map(|&d| 5f32.powf(1e-4 * a_clamped * d)).collect();
                let n_samples = render.len();
                for (n, g) in render.iter_mut().enumerate() {
                    let tt = new_start + (new_end - new_start) * n as f32 / n_samples as f32;
                    *g *= interp1d_linear(&t_mel, &gain_at_mel, &[tt])[0];
                }
            }
        }

        // 恢复 scale + soft clip（与 python 版一致）
        for v in render.iter_mut() { *v /= scale; }
        let new_max = render.iter().fold(0f32, |a, &v| a.max(v.abs()));
        if new_max > self.cfg.peak_limit {
            let threshold = 0.8f32;
            for v in render.iter_mut() {
                if v.abs() > threshold {
                    let sign = v.signum();
                    let over = v.abs() - threshold;
                    *v = sign * (threshold + (1.0 - threshold) * (over / (1.0 - threshold)).tanh());
                }
            }
            let peak = render.iter().fold(0f32, |a, &v| a.max(v.abs()));
            if peak > self.cfg.peak_limit {
                let k = self.cfg.peak_limit / peak * 0.98;
                for v in render.iter_mut() { *v *= k; }
            }
        }

        let peak = render.iter().fold(0f32, |a, &v| a.max(v.abs()));
        crate::log::info(&format!(
            "render done: {} samples ({:.2}s), peak {:.4}, total {:.3}s",
            render.len(),
            render.len() as f32 / self.cfg.sample_rate as f32,
            peak,
            t_render_start.elapsed().as_secs_f32()
        ));
        Ok(render)
    }
}

pub struct RenderArgs {
    pub in_file: std::path::PathBuf,
    pub out_file: std::path::PathBuf,
    pub pitch: i32,
    pub velocity: f32,
    pub flags: String,
    pub offset: f32,
    pub length: i32,
    pub consonant: f32,
    pub cutoff: f32,
    pub volume: f32,
    pub modulation: f32,
    pub tempo: f32,
    pub pitchbend: Vec<i32>,
}

impl RenderArgs {
    /// 从 HTTP 参数串构造（与 python split_arguments + Resampler 参数顺序一致）
    /// 格式：in_file out_file pitch velocity flags offset length consonant cutoff volume modulation tempo pitch_string
    pub fn from_str(s: &str) -> Result<RenderArgs, String> {
        let parts: Vec<&str> = s.split_whitespace().collect();
        if parts.len() < 13 {
            return Err(format!("expected >=13 args, got {}: {s}", parts.len()));
        }
        let n = parts.len();
        let in_file = std::path::PathBuf::from(parts[n - 13]);
        let out_file = std::path::PathBuf::from(parts[n - 12]);
        let pitch = note_to_midi(parts[n - 11])?;
        let velocity: f32 = parts[n - 10].parse().map_err(|_| "bad velocity")?;
        let flags = parts[n - 9].to_string();
        let offset: f32 = parts[n - 8].parse().map_err(|_| "bad offset")?;
        let length: i32 = parts[n - 7].parse().map_err(|_| "bad length")?;
        let consonant: f32 = parts[n - 6].parse().map_err(|_| "bad consonant")?;
        let cutoff: f32 = parts[n - 5].parse().map_err(|_| "bad cutoff")?;
        let volume: f32 = parts[n - 4].parse().map_err(|_| "bad volume")?;
        let modulation: f32 = parts[n - 3].parse().map_err(|_| "bad modulation")?;
        let tempo: f32 = parts[n - 2].trim_start_matches('!').parse().map_err(|_| "bad tempo")?;
        let pitchbend = pitch_string_to_cents(parts[n - 1])?;
        Ok(RenderArgs {
            in_file, out_file, pitch, velocity, flags, offset, length,
            consonant, cutoff, volume, modulation, tempo, pitchbend,
        })
    }
}

pub fn save_wav(path: &Path, x: &[f32], sample_rate: usize) -> Result<(), String> {
    let spec = hound::WavSpec {
        channels: 1,
        sample_rate: sample_rate as u32,
        bits_per_sample: 16,
        sample_format: hound::SampleFormat::Int,
    };
    let mut writer = hound::WavWriter::create(path, spec).map_err(|e| e.to_string())?;
    for &v in x {
        let s = (v.clamp(-1.0, 1.0) * 32767.0) as i16;
        writer.write_sample(s).map_err(|e| e.to_string())?;
    }
    writer.finalize().map_err(|e| e.to_string())
}
