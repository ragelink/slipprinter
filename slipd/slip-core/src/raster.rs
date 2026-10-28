//! Pages as bit images (ESC *).
//!
//! Each 8-dot band prints at 80 dpi (single density) or 160 dpi (double) across,
//! but only 60 dpi down, so dots aren't square. Pages arrive at whatever
//! resolution the sender rendered them, and are resampled onto that grid.

pub const DPI_DOWN: f64 = 60.0;
/// Band height in dots, and the feed (in 1/60") that makes bands touch.
const BAND: usize = 8;
/// The longest blank stretch fed in one ESC J: a multiple of a band, since the
/// head can't feed less than 8/60" at a time.
const MAX_FEED: usize = 248;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Density {
    Single,
    Double,
}

impl Density {
    pub fn dpi_across(self) -> f64 {
        match self {
            Density::Single => 80.0,
            Density::Double => 160.0,
        }
    }

    /// The print band, in dots.
    pub fn max_width(self) -> usize {
        match self {
            Density::Single => 210,
            Density::Double => 420,
        }
    }

    fn mode(self) -> u8 {
        match self {
            Density::Single => 0,
            Density::Double => 1,
        }
    }
}

/// 8-bit grayscale, row by row; 0 is black, 255 is paper.
#[derive(Clone, Debug, PartialEq)]
pub struct Gray {
    pub width: usize,
    pub height: usize,
    pub pixels: Vec<u8>,
}

/// 1-bit, row by row; `true` is a printed dot.
#[derive(Clone, Debug, PartialEq)]
pub struct Dots {
    pub width: usize,
    pub height: usize,
    pub black: Vec<bool>,
}

impl Dots {
    pub fn get(&self, x: usize, y: usize) -> bool {
        self.black[y * self.width + x]
    }

    /// The left `width` dots of every row.
    pub fn crop_width(&self, width: usize) -> Dots {
        let width = width.min(self.width);
        let black = self.black.chunks(self.width.max(1)).flat_map(|row| &row[..width]).copied().collect();
        Dots { width, height: self.height, black }
    }
}

/// Area-average `src` onto `n_out` samples.
fn box_resample(src: &[f32], n_out: usize) -> Vec<f32> {
    let scale = src.len() as f64 / n_out as f64;
    (0..n_out)
        .map(|i| {
            let (start, end) = (i as f64 * scale, (i + 1) as f64 * scale);
            let mut sum = 0.0;
            for (j, &v) in src.iter().enumerate().take(end.ceil() as usize).skip(start.floor() as usize) {
                let weight = end.min(j as f64 + 1.0) - start.max(j as f64);
                sum += v as f64 * weight;
            }
            (sum / scale) as f32
        })
        .collect()
}

/// A page rendered at `dpi_x` by `dpi_y`, resampled onto the printer's dot grid.
pub fn resample(page: &Gray, dpi_x: f64, dpi_y: f64, density: Density) -> Gray {
    let out_w = ((page.width as f64 * density.dpi_across() / dpi_x).round() as usize).max(1);
    let out_h = ((page.height as f64 * DPI_DOWN / dpi_y).round() as usize).max(1);
    let rows: Vec<Vec<f32>> = page
        .pixels
        .chunks(page.width)
        .map(|row| box_resample(&row.iter().map(|&v| v as f32).collect::<Vec<_>>(), out_w))
        .collect();
    let mut pixels = vec![0u8; out_w * out_h];
    for x in 0..out_w {
        let column: Vec<f32> = rows.iter().map(|row| row[x]).collect();
        for (y, v) in box_resample(&column, out_h).into_iter().enumerate() {
            pixels[y * out_w + x] = v.round().clamp(0.0, 255.0) as u8;
        }
    }
    Gray { width: out_w, height: out_h, pixels }
}

/// Dots wherever the page is darker than `level`.
pub fn threshold(page: &Gray, level: u8) -> Dots {
    let black = page.pixels.iter().map(|&v| v < level).collect();
    Dots { width: page.width, height: page.height, black }
}

/// Floyd–Steinberg error diffusion, for photos and shading.
pub fn dither(page: &Gray) -> Dots {
    let (w, h) = (page.width, page.height);
    let mut buf: Vec<f32> = page.pixels.iter().map(|&v| v as f32).collect();
    let mut black = vec![false; w * h];
    for y in 0..h {
        for x in 0..w {
            let i = y * w + x;
            let old = buf[i];
            let new = if old < 128.0 { 0.0 } else { 255.0 };
            black[i] = new == 0.0;
            let err = old - new;
            if x + 1 < w {
                buf[i + 1] += err * 7.0 / 16.0;
            }
            if y + 1 < h {
                if x > 0 {
                    buf[i + w - 1] += err * 3.0 / 16.0;
                }
                buf[i + w] += err * 5.0 / 16.0;
                if x + 1 < w {
                    buf[i + w + 1] += err / 16.0;
                }
            }
        }
    }
    Dots { width: w, height: h, black }
}

/// 8-dot bands of column bytes, top dot in the MSB.
pub fn bands(dots: &Dots) -> Vec<Vec<u8>> {
    (0..dots.height)
        .step_by(BAND)
        .map(|top| {
            (0..dots.width)
                .map(|x| {
                    (0..BAND)
                        .filter(|bit| top + bit < dots.height && dots.get(x, top + bit))
                        .fold(0u8, |byte, bit| byte | 1 << (7 - bit))
                })
                .collect()
        })
        .collect()
}

/// ESC * for one 8-dot band.
pub fn bit_image(columns: &[u8], density: Density) -> Vec<u8> {
    let n = columns.len();
    let mut out = vec![0x1b, b'*', density.mode(), (n & 0xFF) as u8, (n >> 8) as u8];
    out.extend_from_slice(columns);
    out
}

/// Print the line and feed `units`/60 inch (ESC J).
pub fn feed(units: u8) -> [u8; 3] {
    [0x1b, b'J', units]
}

/// Every band, then an exact 8/60" feed so the bands touch. Same bytes as the
/// Python package's `images.image_job`.
pub fn image_job(dots: &Dots, density: Density) -> Vec<u8> {
    let mut out = Vec::new();
    for band in bands(dots) {
        out.extend(bit_image(&band, density));
        out.extend(feed(BAND as u8));
    }
    out
}

/// Like [`image_job`], but for whole pages, which are mostly paper: blank bands
/// become feeds, trailing blank columns aren't sent, and nothing follows the last
/// printed band.
pub fn page_job(dots: &Dots, density: Density) -> Vec<u8> {
    let mut out = Vec::new();
    let mut blank = 0;
    for band in bands(dots) {
        let used = band.iter().rposition(|&b| b != 0).map_or(0, |i| i + 1);
        if used == 0 {
            blank += BAND;
            continue;
        }
        while blank > 0 {
            let units = blank.min(MAX_FEED);
            out.extend(feed(units as u8));
            blank -= units;
        }
        out.extend(bit_image(&band[..used], density));
        out.extend(feed(BAND as u8));
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    fn gray(width: usize, height: usize, f: impl Fn(usize, usize) -> u8) -> Gray {
        let pixels = (0..height).flat_map(|y| (0..width).map(move |x| (x, y))).map(|(x, y)| f(x, y)).collect();
        Gray { width, height, pixels }
    }

    #[test]
    fn box_resample_averages_areas() {
        assert_eq!(box_resample(&[0.0, 255.0, 0.0, 255.0], 2), [127.5, 127.5]);
        assert_eq!(box_resample(&[10.0, 20.0, 30.0], 3), [10.0, 20.0, 30.0]);
        assert_eq!(box_resample(&[0.0, 0.0, 255.0], 2), [0.0, 170.0]); // 1.5 samples each
    }

    #[test]
    fn resample_lands_on_the_dot_grid() {
        // A 2.625" x 1" page at 300 dpi is the full band (210 dots) by 60 dots.
        let page = gray(788, 300, |_, _| 255);
        let out = resample(&page, 300.0, 300.0, Density::Single);
        assert_eq!((out.width, out.height), (210, 60));
        let double = resample(&page, 300.0, 300.0, Density::Double);
        assert_eq!((double.width, double.height), (420, 60));
    }

    #[test]
    fn resample_keeps_solid_areas_solid() {
        let page = gray(300, 300, |x, _| if x < 150 { 0 } else { 255 });
        let out = resample(&page, 300.0, 300.0, Density::Single);
        assert_eq!(out.pixels[0], 0);
        assert_eq!(out.pixels[out.width - 1], 255);
    }

    #[test]
    fn threshold_is_darker_than_level() {
        let dots = threshold(&gray(3, 1, |x, _| [0, 127, 128][x]), 128);
        assert_eq!(dots.black, [true, true, false]);
    }

    #[test]
    fn dither_shades_mid_gray_about_half() {
        let dots = dither(&gray(64, 64, |_, _| 128));
        let share = dots.black.iter().filter(|&&b| b).count() as f64 / dots.black.len() as f64;
        assert!((0.45..0.55).contains(&share), "{share}");
        assert!(dither(&gray(8, 8, |_, _| 255)).black.iter().all(|&b| !b));
    }

    #[test]
    fn bands_put_the_top_dot_in_the_msb() {
        let dots = Dots { width: 2, height: 9, black: (0..18).map(|i| i == 0 || i == 17).collect() };
        assert_eq!(bands(&dots), [vec![0x80, 0x00], vec![0x00, 0x80]]);
    }

    #[test]
    fn bit_image_header() {
        assert_eq!(bit_image(&[1, 2], Density::Single), [0x1b, b'*', 0, 2, 0, 1, 2]);
        assert_eq!(bit_image(&[0; 300], Density::Double)[..5], [0x1b, b'*', 1, 44, 1]);
    }

    #[test]
    fn crop_width_keeps_the_left_side() {
        let dots = Dots { width: 3, height: 2, black: vec![true, false, true, false, true, true] };
        assert_eq!(dots.crop_width(2).black, [true, false, false, true]);
    }

    #[test]
    fn page_job_skips_paper() {
        // Band 0 blank, band 1 one dot at x=1, bands 2-3 blank.
        let mut black = vec![false; 4 * 32];
        black[8 * 4 + 1] = true;
        let job = page_job(&Dots { width: 4, height: 32, black }, Density::Single);
        let mut expected = feed(8).to_vec();
        expected.extend(bit_image(&[0x00, 0x80], Density::Single));
        expected.extend(feed(8));
        assert_eq!(job, expected);
    }

    #[test]
    fn page_job_splits_long_feeds_into_whole_bands() {
        let mut black = vec![false; 400];
        black[399] = true; // 49 blank bands, then the dot in band 49
        let job = page_job(&Dots { width: 1, height: 400, black }, Density::Single);
        assert_eq!(job[..6], [0x1b, b'J', 248, 0x1b, b'J', 144]);
    }
}
