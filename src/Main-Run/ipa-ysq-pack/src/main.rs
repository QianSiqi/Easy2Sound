use std::env;
use std::fs::{read_to_string, write};

fn get_base_word(s: &str) -> String {
    if let Some(pos) = s.find('(') {
        s[..pos].trim().to_string()
    } else {
        s.trim().to_string()
    }
    .to_uppercase()
}

// 解析音符块并查找音素
async fn process_note_block(block: &str, g2p: &dyn voirs_g2p::G2p) -> String {
    let mut result = String::new();
    let mut lines = block.lines();
    
    // 第一行是音符编号
    if let Some(note_header) = lines.next() {
        result.push_str(note_header);
        result.push('\n');
    }
    
    // 处理lyric和phoneme行
    for line in lines {
        if line.starts_with("lyric=") {
            result.push_str(line);
            result.push('\n');
        } else if line.starts_with("phoneme=") {
            // 提取lyric的值来查找音素
            let lyric_line = block.lines().find(|l| l.starts_with("lyric="));
            if let Some(lyric_line) = lyric_line {
                let lyric = lyric_line.strip_prefix("lyric=").unwrap_or("").trim();
                if !lyric.is_empty() && lyric != "" {
                    let base_word = get_base_word(lyric);
                    // 使用voirs-g2p库转换英语单词到音素
                    match g2p.to_phonemes(&base_word, Some(voirs_g2p::LanguageCode::EnUs)).await {
                        Ok(phonemes) => {
                            // 将音素向量转换为逗号分隔的字符串
                            let phoneme_str = phonemes.iter()
                                .map(|p| p.effective_symbol().to_string())
                                .collect::<Vec<String>>()
                                .join(",");
                            result.push_str(&format!("phoneme={}", phoneme_str));
                        }
                        Err(_) => {
                            // 如果转换失败，直接填入lyric本身
                            result.push_str(&format!("phoneme={}", lyric));
                        }
                    }
                } else {
                    result.push_str("phoneme=");
                }
            } else {
                result.push_str("phoneme=");
            }
            result.push('\n');
        } else {
            result.push_str(line);
            result.push('\n');
        }
    }
    
    result
}

// 处理整个temp.e2s文件
async fn process_temp_file(file_content: &str, g2p: &dyn voirs_g2p::G2p) -> String {
    let lines: Vec<&str> = file_content.lines().collect();
    let mut result = String::new();
    let mut current_block = String::new();
    let mut in_note_section = false;
    
    for line in lines {
        // 检查是否是音符块的开始（以数字:开头的行）
        if line.chars().next().map_or(false, |c| c.is_digit(10)) && line.contains(':') {
            // 如果之前有积压的块，先处理它
            if !current_block.is_empty() {
                if in_note_section {
                    // 如果在音符区域，处理当前音符块
                    result.push_str(&process_note_block(&current_block, g2p).await);
                } else {
                    // 如果不在音符区域，直接添加（这是配置部分）
                    result.push_str(&current_block);
                }
            }
            // 开始新的音符块
            current_block.clear();
            current_block.push_str(line);
            current_block.push('\n');
            in_note_section = true;
        } else {
            // 不是以数字:开头的行
            current_block.push_str(line);
            current_block.push('\n');
        }
    }
    
    // 处理最后一个块
    if !current_block.is_empty() {
        if in_note_section {
            result.push_str(&process_note_block(&current_block, g2p).await);
        } else {
            result.push_str(&current_block);
        }
    }
    
    result
}

#[tokio::main]
async fn main() {
    let args: Vec<String> = env::args().collect();
    
    // 需要一个参数（temp.e2s文件路径）
    if args.len() < 2 {
        eprintln!("Usage: {} <temp.e2s_file_path>", args[0]);
        std::process::exit(1);
    }

    let file_path = &args[1];

    // 初始化英语G2P转换器
    let g2p = match voirs_g2p::english::new() {
        Ok(g2p) => Box::new(g2p) as Box<dyn voirs_g2p::G2p>,
        Err(e) => {
            eprintln!("Error initializing G2P: {}", e);
            std::process::exit(1);
        }
    };

    // 读取temp.e2s文件
    let file_content = match read_to_string(file_path) {
        Ok(content) => content,
        Err(e) => {
            eprintln!("Error reading file: {}", e);
            std::process::exit(1);
        }
    };

    // 处理文件内容
    let processed_content = process_temp_file(&file_content, g2p.as_ref()).await;

    // 覆盖保存文件
    match write(file_path, processed_content) {
        Ok(_) => {
            println!("File processed successfully!");
        }
        Err(e) => {
            eprintln!("Error writing file: {}", e);
            std::process::exit(1);
        }
    }
}