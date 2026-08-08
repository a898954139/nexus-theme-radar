// Clarity only records a page view on a real document load. This app routes
// through the hash (`#page=momentum`), so without reporting those transitions
// every session would collapse into a single page in the dashboard.

const PAGE_LABELS: Record<string, string> = {
  index: '題材雷達',
  momentum: '題材動能',
  flows: '資金流向',
  stock: '個股',
  sources: '源狀態'
};

type ClarityFn = (...args: unknown[]) => void;

function clarity(): ClarityFn | null {
  const fn = (window as unknown as { clarity?: ClarityFn }).clarity;
  return typeof fn === 'function' ? fn : null;
}

function currentPageLabel(): string {
  const params = new URLSearchParams(window.location.hash.replace(/^#/, ''));
  const page = params.get('page') ?? 'index';
  return PAGE_LABELS[page] ?? PAGE_LABELS.index;
}

function report(): void {
  // The snippet queues calls until the tag loads, so an early call is safe.
  // A missing `clarity` means the tag was blocked; reporting is then a no-op.
  clarity()?.('set', 'page', currentPageLabel());
}

export function startClarityRouteReporting(): () => void {
  report();
  window.addEventListener('hashchange', report);
  return () => window.removeEventListener('hashchange', report);
}
