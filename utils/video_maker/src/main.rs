#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod app;
mod binaries;
mod encoder;
mod ytdlp;

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let bins = match binaries::extract() {
        Ok(b) => b,
        Err(e) => {
            rfd::MessageDialog::new()
                .set_title("초기화 실패")
                .set_description(format!("내장 도구(ffmpeg/yt-dlp) 준비 중 오류: {e}"))
                .set_level(rfd::MessageLevel::Error)
                .show();
            return Err(e.into());
        }
    };

    let options = eframe::NativeOptions {
        viewport: eframe::egui::ViewportBuilder::default()
            .with_inner_size([680.0, 760.0])
            .with_min_inner_size([520.0, 540.0])
            .with_title("앨범 커버 영상 생성기"),
        ..Default::default()
    };

    eframe::run_native(
        "앨범 커버 영상 생성기",
        options,
        Box::new(move |cc| {
            app::setup_fonts(&cc.egui_ctx);
            Ok(Box::new(app::App::new(bins.ffmpeg, bins.yt_dlp)))
        }),
    )?;

    Ok(())
}
