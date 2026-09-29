themeLabel();
paintTape();
paintHome();
paintHoldings();
paintOverview();
paintResearch();
paintSheet();
// Positions is painted at boot even though Home is what opens, so the
// first switch is instant. The rail, the head, the thesis and the weight strip
// all render fine into a hidden container because none of them measures
// anything. The chart is the exception and is deliberately NOT built here -
// see paintChart - so the first switch to Positions is what constructs it.
// ROUTING is held true across the first paint so none of it writes a route.
// Without the guard the boot select() below stamps #/overview into the address
// bar before applyHash ever reads it, and a cold load of a shared link lands
// on the Overview having just overwritten the link that asked for somewhere
// else. Build first, then read the URL, then stamp what we actually resolved.
ROUTING = true;
setView('home');
if (ROWS.length) {
  select(state.sym);
} else {
  const l = $('#list');
  if (l) l.innerHTML = '<div class="empty">No positions and no watchlist rows.</div>';
}
ROUTING = false;
applyHash();
syncHash();

