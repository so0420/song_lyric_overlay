use anyhow::{anyhow, Context, Result};
use std::io::{BufRead, BufReader, Read};
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::sync::mpsc::Sender;

#[derive(Debug)]
pub enum Progress {
    Status(String),
    Percent(f32),
    JobSucceeded(PathBuf),
    JobFailed { label: String, message: String },
    AllDone,
}

pub struct EncodeJob {
    pub ffmpeg_path: PathBuf,
    pub image_path: PathBuf,
    pub audio_path: PathBuf,
    pub output_path: PathBuf,
}

pub fn run_job(job: &EncodeJob, tx: &Sender<Progress>) -> Result<()> {
    let duration_us = probe_duration_us(&job.ffmpeg_path, &job.audio_path)
        .context("오디오 길이 확인 실패")?;

    let _ = tx.send(Progress::Percent(0.0));

    let mut cmd = Command::new(&job.ffmpeg_path);
    cmd.args([
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-loop",
        "1",
        "-framerate",
        "2",
        "-i",
    ]);
    cmd.arg(&job.image_path);
    cmd.arg("-i");
    cmd.arg(&job.audio_path);
    cmd.args([
        "-c:v",
        "libx264",
        "-tune",
        "stillimage",
        "-preset",
        "veryfast",
        "-crf",
        "23",
        "-pix_fmt",
        "yuv420p",
        "-vf",
        "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2:black",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-shortest",
        "-movflags",
        "+faststart",
        "-progress",
        "pipe:1",
        "-nostats",
    ]);
    cmd.arg(&job.output_path);
    cmd.stdin(Stdio::null());
    cmd.stdout(Stdio::piped());
    cmd.stderr(Stdio::piped());

    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        const CREATE_NO_WINDOW: u32 = 0x0800_0000;
        cmd.creation_flags(CREATE_NO_WINDOW);
    }

    let mut child = cmd.spawn().context("ffmpeg 실행 실패")?;
    let stdout = child.stdout.take().unwrap();
    let stderr = child.stderr.take().unwrap();

    let stderr_handle = std::thread::spawn(move || {
        let mut buf = String::new();
        let _ = BufReader::new(stderr).read_to_string(&mut buf);
        buf
    });

    let reader = BufReader::new(stdout);
    for line in reader.lines().map_while(|l| l.ok()) {
        if let Some(v) = line.strip_prefix("out_time_us=") {
            if let Ok(us) = v.trim().parse::<i64>() {
                if us > 0 && duration_us > 0 {
                    let pct = (us as f32 / duration_us as f32).clamp(0.0, 0.999);
                    let _ = tx.send(Progress::Percent(pct));
                }
            }
        } else if line.starts_with("progress=end") {
            let _ = tx.send(Progress::Percent(1.0));
        }
    }

    let status = child.wait()?;
    let stderr_text = stderr_handle.join().unwrap_or_default();

    if !status.success() {
        return Err(anyhow!(
            "ffmpeg 종료 코드 {:?}: {}",
            status.code(),
            stderr_text.lines().rev().take(5).collect::<Vec<_>>().join(" | ")
        ));
    }
    Ok(())
}

fn probe_duration_us(ffmpeg: &Path, audio: &Path) -> Result<i64> {
    let mut cmd = Command::new(ffmpeg);
    cmd.args(["-hide_banner", "-i"]);
    cmd.arg(audio);
    cmd.stdin(Stdio::null());
    cmd.stdout(Stdio::null());
    cmd.stderr(Stdio::piped());

    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        const CREATE_NO_WINDOW: u32 = 0x0800_0000;
        cmd.creation_flags(CREATE_NO_WINDOW);
    }

    let output = cmd.output()?;
    let stderr = String::from_utf8_lossy(&output.stderr);

    let idx = stderr
        .find("Duration: ")
        .ok_or_else(|| anyhow!("Duration 행을 찾을 수 없음"))?;
    let rest = &stderr[idx + "Duration: ".len()..];
    let end = rest.find(',').unwrap_or(rest.len());
    parse_duration(rest[..end].trim())
}

fn parse_duration(s: &str) -> Result<i64> {
    let parts: Vec<&str> = s.split(':').collect();
    if parts.len() != 3 {
        return Err(anyhow!("잘못된 duration 형식: {s}"));
    }
    let h: f64 = parts[0].parse()?;
    let m: f64 = parts[1].parse()?;
    let sec: f64 = parts[2].parse()?;
    let total = h * 3600.0 + m * 60.0 + sec;
    Ok((total * 1_000_000.0) as i64)
}
