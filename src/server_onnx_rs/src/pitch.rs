// pitch 相关：UTAU 音名 → MIDI，pitchbend Base64/RLE → cents 序列
// 与 server_onnx.py 的 note_to_midi / pitch_string_to_cents 对齐

const NOTES: [&str; 12] = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"];

fn to_uint6(c: u8) -> Result<u8, String> {
    match c {
        b'a'..=b'z' => Ok(c - 71),
        b'A'..=b'Z' => Ok(c - 65),
        b'0'..=b'9' => Ok(c + 4),
        b'+' => Ok(62),
        b'/' => Ok(63),
        _ => Err(format!("invalid base64 char: {}", c as char)),
    }
}

fn to_int12(a: u8, b: u8) -> Result<i32, String> {
    let uint12 = ((to_uint6(a)? as i32) << 6) | to_uint6(b)? as i32;
    Ok(if uint12 >> 11 & 1 == 1 { uint12 - 4096 } else { uint12 })
}

/// UTAU pitchbend 字符串（Base64 + RLE，'#' 分隔）→ 以分为单位的序列
pub fn pitch_string_to_cents(x: &str) -> Result<Vec<i32>, String> {
    let pitch: Vec<&str> = x.split('#').collect();
    let mut res: Vec<i32> = Vec::new();
    let mut i = 0;
    while i < pitch.len() {
        if i + 1 < pitch.len() {
            let (pitch_str, rle) = (pitch[i], pitch[i + 1]);
            let stream = to_int12_stream(pitch_str)?;
            let last = *stream.last().unwrap_or(&0);
            res.extend(stream);
            let rle_n: usize = rle.parse().map_err(|_| format!("bad rle: {rle}"))?;
            res.extend(std::iter::repeat(last).take(rle_n));
        } else {
            res.extend(to_int12_stream(pitch[i])?);
        }
        i += 2;
    }
    // 全部相同 → 全零（与 python 一致）
    if res.iter().all(|&v| v == res[0]) {
        res.fill(0);
        return Ok(res);
    }
    res.push(0); // 末尾补零
    Ok(res)
}

fn to_int12_stream(s: &str) -> Result<Vec<i32>, String> {
    let bytes = s.as_bytes();
    if bytes.len() % 2 != 0 {
        return Err(format!("odd base64 length: {s}"));
    }
    let mut out = Vec::with_capacity(bytes.len() / 2);
    for i in (0..bytes.len()).step_by(2) {
        out.push(to_int12(bytes[i], bytes[i + 1])?);
    }
    Ok(out)
}

/// 音名（如 "C4", "G#4", "F#3"）→ MIDI 编号（python note_to_midi 的 octave+1 约定）
pub fn note_to_midi(s: &str) -> Result<i32, String> {
    let bytes = s.as_bytes();
    let (mut i, mut note_name) = (0, String::new());
    while i < bytes.len() && bytes[i].is_ascii_alphabetic() {
        note_name.push(bytes[i] as char);
        i += 1;
    }
    // 升号（#）属于音名的一部分
    if i < bytes.len() && bytes[i] == b'#' {
        note_name.push('#');
        i += 1;
    }
    let octave: i32 = s[i..].trim().parse().map_err(|_| format!("bad note: {s}"))?;
    let idx = NOTES.iter().position(|&n| n == note_name).ok_or(format!("bad note name: {note_name}"))?;
    Ok((octave + 1) * 12 + idx as i32)
}

pub fn midi_to_hz(x: f32) -> f32 {
    440.0 * 2f32.powf((x - 69.0) / 12.0)
}
