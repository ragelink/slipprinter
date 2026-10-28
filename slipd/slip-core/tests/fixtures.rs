//! Same bytes as the Python package, pinned by shared fixtures (see tests/test_rust_fixtures.py).

use slip_core::raster::{image_job, Density, Dots};

const WIDTH: usize = 45;
const HEIGHT: usize = 20;

/// Diagonal stripes plus a diagonal line; the same formula is in the Python test.
fn pattern() -> Dots {
    let black = (0..HEIGHT).flat_map(|y| (0..WIDTH).map(move |x| (x * 3 + y * 5) % 7 < 3 || x == y)).collect();
    Dots { width: WIDTH, height: HEIGHT, black }
}

#[test]
fn single_density_matches_python() {
    assert_eq!(image_job(&pattern(), Density::Single), include_bytes!("fixtures/pattern-single.bin"));
}

#[test]
fn double_density_matches_python() {
    assert_eq!(image_job(&pattern(), Density::Double), include_bytes!("fixtures/pattern-double.bin"));
}
