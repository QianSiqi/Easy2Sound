// wav 读取：hound 读取 + 简单线性重采样到 sample_rate
// （与 python 版 read_wav 对齐；44.1k 输入不重采样）
use std::path::Path;

pub fn read_wav(path: &Path, sample_rate: usize) -> Result<Vec<f32>, String> {
    let mut reader = hound::WavReader::open(path).map_err(|e| e.to_string())?;
    let spec = reader.spec();
    let n_channels = spec.channels as usize;
    let fs = spec.sample_rate as usize;
    let samples: Vec<f32> = match spec.sample_format {
        hound::SampleFormat::Float => {
            reader.samples::<f32>().collect::<Result<Vec<_>, _>>().map_err(|e| e.to_string())?
        }
        hound::SampleFormat::Int => {
            let bits = spec.bits_per_sample;
            match bits {
                16 => reader.samples::<i16>().collect::<Result<Vec<_>, _>>().map_err(|e| e.to_string())?
                    .into_iter().map(|s| s as f32 / 32768.0).collect(),
                24 => reader.samples::<i32>().collect::<Result<Vec<_>, _>>().map_err(|e| e.to_string())?
                    .into_iter().map(|s| (s as f32) / 8388608.0).collect(),
                32 => reader.samples::<i32>().collect::<Result<Vec<_>, _>>().map_err(|e| e.to_string())?
                    .into_iter().map(|s| s as f32 / 2147483648.0).collect(),
                b => return Err(format!("unsupported bits_per_sample: {b}")),
            }
        }
    };

    // 多声道取平均
    let mono: Vec<f32> = if n_channels > 1 {
        samples.chunks_exact(n_channels).map(|c| c.iter().sum::<f32>() / n_channels as f32).collect()
    } else {
        samples
    };

    if fs == sample_rate {
        Ok(mono)
    } else {
        Ok(resample_linear(&mono, fs, sample_rate))
    }
}

// 线性插值重采样（resampy 是 sinc 重采样，这里简化；仅在非 44.1k 输入时触发）
fn resample_linear(x: &[f32], fs_in: usize, fs_out: usize) -> Vec<f32> {
    let n_out = (x.len() as f64 * fs_out as f64 / fs_in as f64) as usize;
    let mut out = Vec::with_capacity(n_out);
    for i in 0..n_out {
        let pos = i as f64 * fs_in as f64 / fs_out as f64;
        let idx = pos.floor() as usize;
        let frac = (pos - idx as f64) as f32;
        let a = x[idx.min(x.len() - 1)];
        let b = x[(idx + 1).min(x.len() - 1)];
        out.push(a + (b - a) * frac);
    }
    out
}
