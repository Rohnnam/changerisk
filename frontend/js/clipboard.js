import { announce } from './dom.js';

/** Copy text. Falls back to a hidden textarea where the async clipboard API is refused. */
export async function copyText(text, what = 'Copied') {
  let ok = false;
  try {
    await navigator.clipboard.writeText(text);
    ok = true;
  } catch {
    const area = document.createElement('textarea');
    area.value = text;
    area.setAttribute('readonly', '');
    area.className = 'visually-hidden';
    document.body.append(area);
    area.select();
    try {
      ok = document.execCommand('copy');
    } catch {
      ok = false;
    }
    area.remove();
  }
  announce(ok ? `${what} to the clipboard.` : 'Copying failed. Select the text and copy it by hand.');
  return ok;
}
