function createSlider(container, beforeUrl, afterUrl, viewport = 'desktop') {
  const slider = document.createElement('div');
  slider.className = 'ba-slider';

  const dimensions = viewport === 'mobile' ? [390, 844] : [1280, 800];
  const makeImage = (url, label) => {
    const img = new Image(...dimensions);
    img.src = url;
    img.alt = label;
    img.decoding = 'async';
    img.draggable = false;
    return img;
  };
  const before = makeImage(beforeUrl, 'Before the repair');
  before.className = 'ba-before';
  const after = makeImage(afterUrl, 'After the repair');

  const control = document.createElement('input');
  control.type = 'range';
  control.className = 'ba-control';
  control.value = '50';
  control.setAttribute('aria-label', 'Before image shown');
  control.setAttribute('aria-valuetext', '50%');
  control.addEventListener('input', () => {
    slider.style.setProperty('--split', control.value + '%');
    control.setAttribute('aria-valuetext', control.value + '%');
  });

  const handle = document.createElement('span');
  handle.className = 'ba-handle';
  handle.setAttribute('aria-hidden', 'true');
  slider.append(after, before, handle, control);
  container.replaceChildren(slider);
}
