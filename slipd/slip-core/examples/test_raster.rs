//! Prints a test raster on real paper: a gray ramp (dithered), solid bars and a
//! circle that should come out round. Insert a slip within two minutes.
//!
//! cargo run --example test_raster [-- PORT]

use slip_core::link::EJECT;
use slip_core::raster::{dither, page_job, resample, Density, Gray};
use slip_core::serial::SerialTransport;
use slip_core::Printer;

fn main() -> Result<(), Box<dyn std::error::Error>> {
    // 2.5" x 1.5" at 300 dpi, the way a phone would render it.
    let (w, h) = (750, 450);
    let pixels = (0..h)
        .flat_map(|y| (0..w).map(move |x| (x, y)))
        .map(|(x, y)| {
            let (dx, dy) = (x as f64 - 560.0, y as f64 - 225.0);
            let ring = (dx.hypot(dy) - 150.0).abs() < 12.0;
            if ring || (y < 60 && x % 100 < 50) {
                0
            } else if x < 360 && y > 90 {
                (x * 255 / 360) as u8
            } else {
                255
            }
        })
        .collect();
    let page = Gray { width: w, height: h, pixels };
    let dots = dither(&resample(&page, 300.0, 300.0, Density::Single));
    let job = page_job(&dots.crop_width(Density::Single.max_width()), Density::Single);

    let port = std::env::args().nth(1);
    let mut printer = Printer::new(SerialTransport::open(port.as_deref())?);
    println!("insert a slip ({} bytes to print)", job.len());
    printer.print_job(&job, EJECT, 120.0, 120.0)?;
    println!("printed");
    Ok(())
}
