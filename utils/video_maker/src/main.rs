#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod app;
mod encoder;
mod ffmpeg;

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let ffmpeg_path = match ffmpeg::extract_ffmpeg() {
        Ok(p) => p,
        Err(e) => {
            rfd::MessageDialog::new()
                .set_title("초기화 실패")
                .set_description(format!("ffmpeg 준비 중 오류: {e}"))
                .set_level(rfd::MessageLevel::Error)
                .show();
            return Err(e.into());
        }
    };

    let options = eframe::NativeOptions {
        viewport: eframe::egui::ViewportBuilder::default()
            .with_inner_size([680.0, 640.0])
            .with_min_inner_size([520.0, 480.0])
            .with_title("앨범 커버 영상 생성기"),
        ..Default::default()
    };

    eframe::run_native(
        "앨범 커버 영상 생성기",
        options,
        Box::new(move |cc| {
            app::setup_fonts(&cc.egui_ctx);
            Ok(Box::new(app::App::new(ffmpeg_path)))
        }),
    )?;

    Ok(())
}
