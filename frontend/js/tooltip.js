// One shared tooltip element. It enhances hover and focus; nothing depends on it for meaning.

function node() {
  return document.getElementById('tip');
}

export function showTip(x, y, content) {
  const tip = node();
  if (!tip) return;
  tip.replaceChildren(...[].concat(content));
  tip.hidden = false;
  const box = tip.getBoundingClientRect();
  const left = Math.min(Math.max(8, x - box.width / 2), window.innerWidth - box.width - 8);
  const above = y - box.height - 14;
  const top = above < 8 ? y + 18 : above;
  tip.style.setProperty('--tip-x', `${Math.round(left)}px`);
  tip.style.setProperty('--tip-y', `${Math.round(top)}px`);
}

export function hideTip() {
  const tip = node();
  if (tip) tip.hidden = true;
}

/** Show `content()` while the pointer is over `el` or it has keyboard focus. */
export function attachTip(el, content) {
  const at = (event) => {
    const r = el.getBoundingClientRect();
    const x = event.clientX || r.left + r.width / 2;
    const y = event.clientY || r.top;
    showTip(x, event.clientX ? y : r.top, content());
  };
  el.addEventListener('pointermove', at);
  el.addEventListener('pointerleave', hideTip);
  el.addEventListener('focus', at);
  el.addEventListener('blur', hideTip);
}
