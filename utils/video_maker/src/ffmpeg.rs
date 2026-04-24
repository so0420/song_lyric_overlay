use anyhow::{anyhow, Result};
use std::fs;
use std::io::Cursor;
use std::path::PathBuf;

const FFMPEG_ZST: &[u8] = include_bytes!("../resources/ffmpeg.exe.zst");

pub fn extract_ffmpeg() -> Result<PathBuf> {
    let cache_dir = dirs::cache_dir()
        .ok_or_else(|| anyhow!("cache 디렉터리를 찾을 수 없음"))?
        .join("VideoMaker");
    fs::create_dir_all(&cache_dir)?;

    let stamp = format!("{:016x}", fingerprint(FFMPEG_ZST));
    let ffmpeg_path = cache_dir.join(format!("ffmpeg-{stamp}.exe"));

    if !ffmpeg_path.exists() {
        let decompressed = zstd::decode_all(Cursor::new(FFMPEG_ZST))?;
        let tmp = ffmpeg_path.with_extension("exe.tmp");
        fs::write(&tmp, &decompressed)?;
        fs::rename(&tmp, &ffmpeg_path)?;
    }

    Ok(ffmpeg_path)
}

fn fingerprint(data: &[u8]) -> u64 {
    let mut h: u64 = 0xcbf29ce484222325;
    let sample = &data[..data.len().min(8192)];
    for &b in sample {
        h ^= b as u64;
        h = h.wrapping_mul(0x100000001b3);
    }
    h ^= data.len() as u64;
    h
}
