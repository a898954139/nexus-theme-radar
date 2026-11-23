// Draws Nexus FVG / OB zones on the K-line chart as shaded boxes from the bar
// that formed them to the right edge (lightweight-charts series primitive).
import type { IPrimitivePaneRenderer, IPrimitivePaneView, ISeriesPrimitive, SeriesAttachedParameter, Time } from 'lightweight-charts';
import type { CanvasRenderingTarget2D } from 'fancy-canvas';

export interface ZoneBox { from: string; low: number; high: number; fill: string; stroke: string; label: string }

interface Pixel { x: number; y1: number; y2: number; fill: string; stroke: string; label: string }

class ZonesRenderer implements IPrimitivePaneRenderer {
  constructor(private readonly boxes: Pixel[], private readonly text: string) {}

  draw(target: CanvasRenderingTarget2D) {
    target.useBitmapCoordinateSpace(({ context: ctx, bitmapSize, horizontalPixelRatio: hr, verticalPixelRatio: vr }) => {
      for (const box of this.boxes) {
        const x = Math.max(0, Math.round(box.x * hr));
        const top = Math.round(Math.min(box.y1, box.y2) * vr);
        const height = Math.max(1, Math.round(Math.abs(box.y2 - box.y1) * vr));
        ctx.fillStyle = box.fill;
        ctx.fillRect(x, top, bitmapSize.width - x, height);
        ctx.strokeStyle = box.stroke;
        ctx.lineWidth = Math.max(1, Math.floor(hr));
        ctx.strokeRect(x + 0.5, top + 0.5, bitmapSize.width - x - 1, height - 1);
        ctx.fillStyle = this.text;
        ctx.font = `${Math.round(10 * vr)}px 'Noto Sans TC', system-ui, sans-serif`;
        ctx.textBaseline = 'top';
        ctx.fillText(box.label, x + Math.round(4 * hr), top + Math.round(2 * vr));
      }
    });
  }
}

class ZonesView implements IPrimitivePaneView {
  constructor(private readonly source: NexusZonesPrimitive) {}
  zOrder() { return 'bottom' as const; }
  renderer() { return new ZonesRenderer(this.source.pixels(), this.source.textColor); }
}

export class NexusZonesPrimitive implements ISeriesPrimitive<Time> {
  private param: SeriesAttachedParameter<Time> | null = null;
  private readonly views: ZonesView[];

  constructor(private readonly boxes: ZoneBox[], readonly textColor: string) {
    this.views = [new ZonesView(this)];
  }

  attached(param: SeriesAttachedParameter<Time>) { this.param = param; }
  detached() { this.param = null; }
  updateAllViews() {}
  paneViews() { return this.views; }

  pixels(): Pixel[] {
    if (!this.param) return [];
    const { chart, series } = this.param;
    const out: Pixel[] = [];
    for (const box of this.boxes) {
      const x = chart.timeScale().timeToCoordinate(box.from as Time);
      const y1 = series.priceToCoordinate(box.high);
      const y2 = series.priceToCoordinate(box.low);
      if (y1 === null || y2 === null) continue;
      out.push({ x: x ?? 0, y1, y2, fill: box.fill, stroke: box.stroke, label: box.label });
    }
    return out;
  }
}
