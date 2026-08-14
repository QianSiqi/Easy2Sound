// 配置：与 server_onnx.py 的 Config 对齐，加载 config.yaml（缺失用默认值）
use std::path::Path;

#[derive(Clone)]
pub struct Config {
    pub sample_rate: usize,
    pub win_size: usize,
    pub hop_size: usize,
    pub origin_hop_size: usize,
    pub n_mels: usize,
    pub n_fft: usize,
    pub mel_fmin: f32,
    pub mel_fmax: f32,
    pub fill: usize,
    pub vocoder_path: String,
    pub hnsep_model_path: String,
    pub wave_norm: bool,
    pub loop_mode: bool,
    pub peak_limit: f32,
    pub onnxruntime_dll: String,
}

impl Default for Config {
    fn default() -> Self {
        Config {
            sample_rate: 44100,
            win_size: 2048,
            hop_size: 512,
            origin_hop_size: 128,
            n_mels: 128,
            n_fft: 2048,
            mel_fmin: 40.0,
            mel_fmax: 16000.0,
            fill: 6,
            vocoder_path: r"pc_nsf_hifigan_44.1k_hop512_128bin_2025.02\model.onnx".into(),
            hnsep_model_path: r"hnsep\vr\model.onnx".into(),
            wave_norm: false,
            loop_mode: false,
            peak_limit: 1.0,
            onnxruntime_dll: String::new(),
        }
    }
}

fn get_str(map: &yaml_rust2::yaml::Hash, key: &str) -> Option<String> {
    map.get(&yaml_rust2::Yaml::String(key.into()))
        .and_then(|v| v.as_str())
        .map(String::from)
}

fn get_f64(map: &yaml_rust2::yaml::Hash, key: &str) -> Option<f64> {
    map.get(&yaml_rust2::Yaml::String(key.into()))
        .and_then(|v| v.as_f64())
}

fn get_i64(map: &yaml_rust2::yaml::Hash, key: &str) -> Option<i64> {
    map.get(&yaml_rust2::Yaml::String(key.into()))
        .and_then(|v| v.as_i64())
}

fn get_bool(map: &yaml_rust2::yaml::Hash, key: &str) -> Option<bool> {
    map.get(&yaml_rust2::Yaml::String(key.into()))
        .and_then(|v| v.as_bool())
}

impl Config {
    pub fn load(dir: &Path) -> Config {
        let mut cfg = Config::default();
        let path = dir.join("config.yaml");
        if !path.exists() {
            println!("config.yaml not found, using defaults");
            return cfg;
        }
        let text = match std::fs::read_to_string(&path) {
            Ok(t) => t,
            Err(e) => {
                println!("failed to read config.yaml: {e}, using defaults");
                return cfg;
            }
        };
        let doc = yaml_rust2::YamlLoader::load_from_str(&text);
        let doc = match doc {
            Ok(d) => d,
            Err(e) => {
                println!("failed to parse config.yaml: {e}, using defaults");
                return cfg;
            }
        };
        let root = doc.first().map(|d| d.as_hash()).flatten();
        let Some(root) = root else {
            return cfg;
        };

        if let Some(m) = root.get(&yaml_rust2::Yaml::String("model".into())).and_then(|v| v.as_hash()) {
            if let Some(p) = get_str(m, "vocoder_path") {
                cfg.vocoder_path = if p.ends_with(".ckpt") {
                    p.replace(".ckpt", ".onnx")
                } else {
                    p
                };
            }
            if let Some(p) = get_str(m, "hnsep_model_path") {
                cfg.hnsep_model_path = if p.ends_with(".pt") {
                    p.replace(".pt", ".onnx")
                } else {
                    p
                };
            }
        }
        if let Some(a) = root.get(&yaml_rust2::Yaml::String("audio".into())).and_then(|v| v.as_hash()) {
            if let Some(v) = get_i64(a, "sample_rate") { cfg.sample_rate = v as usize; }
            if let Some(v) = get_i64(a, "win_size") { cfg.win_size = v as usize; }
            if let Some(v) = get_i64(a, "hop_size") { cfg.hop_size = v as usize; }
            if let Some(v) = get_i64(a, "origin_hop_size") { cfg.origin_hop_size = v as usize; }
            if let Some(v) = get_i64(a, "n_fft") { cfg.n_fft = v as usize; }
            if let Some(v) = get_i64(a, "n_mels") { cfg.n_mels = v as usize; }
            if let Some(v) = get_f64(a, "mel_fmin") { cfg.mel_fmin = v as f32; }
            if let Some(v) = get_f64(a, "mel_fmax") { cfg.mel_fmax = v as f32; }
        }
        if let Some(p) = root.get(&yaml_rust2::Yaml::String("processing".into())).and_then(|v| v.as_hash()) {
            if let Some(v) = get_bool(p, "wave_norm") { cfg.wave_norm = v; }
            if let Some(v) = get_bool(p, "loop_mode") { cfg.loop_mode = v; }
            if let Some(v) = get_f64(p, "peak_limit") { cfg.peak_limit = v as f32; }
            if let Some(v) = get_i64(p, "fill") { cfg.fill = v as usize; }
        }
        cfg
    }
}
