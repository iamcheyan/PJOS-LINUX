use pocket_drivers::{DrawList, FontView, FrameInput, PixelFormat, Rect, RenderResources, Renderer, Surface, Target, TexView};
use pocket_raster::{render_surface, RasterRenderer};
use pocket_spec::draw_op;
use std::cell::Cell;

struct Resources;
impl RenderResources for Resources {
    fn viewport(&self) -> (f32, f32) { (480.0, 320.0) }
    fn raster_revision(&self) -> u64 { 0 }
    fn texture(&self, _: i32) -> Option<TexView<'_>> { None }
    fn font_atlas(&self, _: u8) -> Option<FontView<'_>> { None }
}

struct CountingResources { revision: Cell<u64>, texture_reads: Cell<usize> }
impl RenderResources for CountingResources {
    fn viewport(&self) -> (f32, f32) { (480.0, 320.0) }
    fn raster_revision(&self) -> u64 { self.revision.get() }
    fn texture(&self, _: i32) -> Option<TexView<'_>> {
        self.texture_reads.set(self.texture_reads.get() + 1);
        Some(TexView { pixels: &[255, 0, 0, 255], w: 1, h: 1, psm: pocket_spec::psm::PSM_8888, palette: None, linear: false })
    }
    fn font_atlas(&self, _: u8) -> Option<FontView<'_>> { None }
}

#[test]
fn cached_frame_invalidates_when_resources_or_draw_list_change() {
    let resources = CountingResources { revision: Cell::new(0), texture_reads: Cell::new(0) };
    let mut list = DrawList::new();
    list.words = vec![draw_op::TEX_QUAD, 0, 0, 1 | (1 << 16), 0, 0,
                      1.0f32.to_bits(), 1.0f32.to_bits(), 0xffff_ffff];
    let mut renderer = RasterRenderer::new(1).unwrap();
    let mut output = vec![0; 720 * 480 * 4];
    let mut render = |list: &DrawList| {
        let surface = Surface::new(&mut output, Rect::new(0, 0, 720, 480), 720 * 4, PixelFormat::Argb8888).unwrap();
        let mut frame = FrameInput::new(list, &resources, &[], Target::CpuVisible(surface));
        renderer.render(&mut frame).unwrap();
    };
    render(&list);
    let first = resources.texture_reads.get();
    assert!(first > 0);
    render(&list);
    assert_eq!(resources.texture_reads.get(), first);
    resources.revision.set(1);
    render(&list);
    let changed = resources.texture_reads.get();
    assert!(changed > first);
    list.words[8] = 0x7fff_ffff;
    render(&list);
    assert!(resources.texture_reads.get() > changed);
}

#[test]
fn fractional_renderer_maps_every_output_pixel_and_preserves_stride() {
    let mut list = DrawList::new();
    list.words = vec![draw_op::RECT, 0, 480 | (320 << 16), 0xff22_4466,
                      draw_op::RECT, 1 | (1 << 16), 478 | (318 << 16), 0xffaa_8822];
    for format in [PixelFormat::Argb8888, PixelFormat::Rgb565] {
        let bpp = format.bits_per_pixel() / 8;
        let mut reference = vec![0; 480 * 320 * bpp];
        let mut source = Surface::new(&mut reference, Rect::new(0, 0, 480, 320), 480 * bpp, format).unwrap();
        render_surface(&Resources, &list.words, &mut source, 1).unwrap();
        let stride = 720 * bpp + 7;
        let mut output = vec![0x5a; stride * 480];
        {
            let surface = Surface::new(&mut output, Rect::new(0, 0, 720, 480), stride, format).unwrap();
            let mut frame = FrameInput::new(&list, &Resources, &[], Target::CpuVisible(surface));
            RasterRenderer::new(1).unwrap().render(&mut frame).unwrap();
        }
        for y in 0..480 {
            for x in 0..720 {
                let actual = y * stride + x * bpp;
                let expected = ((y * 2 / 3) * 480 + x * 2 / 3) * bpp;
                assert_eq!(&output[actual..actual + bpp], &reference[expected..expected + bpp]);
            }
            assert!(output[y * stride + 720 * bpp..(y + 1) * stride].iter().all(|byte| *byte == 0x5a));
        }
    }
}
