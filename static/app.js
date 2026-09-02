const loginCard = document.getElementById('loginCard');
const loginForm = document.getElementById('loginForm');
const loginError = document.getElementById('loginError');
const logout = document.getElementById('logout');
const uploadCard = document.getElementById('uploadCard');
const drop = document.getElementById('drop');
const file = document.getElementById('file');
const go = document.getElementById('go');
const status = document.getElementById('status');
const err = document.getElementById('err');
const result = document.getElementById('result');
let chosen = null;

function showAuthenticated(authenticated, desktop = false) {
  loginCard.hidden = authenticated;
  uploadCard.hidden = !authenticated;
  logout.hidden = !authenticated || desktop;
  if (!authenticated) {
    result.hidden = true;
    chosen = null;
    go.disabled = true;
  }
}

async function request(url, options = {}) {
  const response = await fetch(url, options);
  let data = {};
  try {
    data = await response.json();
  } catch (_) {
    data = {};
  }
  if (response.status === 401) {
    showAuthenticated(false);
  }
  if (!response.ok) {
    throw new Error(data.detail || 'No se pudo completar la operación.');
  }
  return data;
}

async function checkSession() {
  try {
    const session = await request('/auth/session');
    showAuthenticated(session.authenticated, session.desktop);
  } catch (_) {
    showAuthenticated(false);
  }
}

loginForm.addEventListener('submit', async (event) => {
  event.preventDefault();
  loginError.textContent = '';
  const body = new FormData(loginForm);
  try {
    await request('/auth/login', { method: 'POST', body });
    loginForm.reset();
    showAuthenticated(true);
  } catch (error) {
    loginError.textContent = error.message;
  }
});

logout.addEventListener('click', async () => {
  await fetch('/auth/logout', { method: 'POST' });
  showAuthenticated(false);
});

drop.addEventListener('click', () => file.click());
drop.addEventListener('keydown', (event) => {
  if (event.key === 'Enter' || event.key === ' ') {
    event.preventDefault();
    file.click();
  }
});
file.addEventListener('change', () => pick(file.files[0]));
['dragover', 'dragenter'].forEach((name) => drop.addEventListener(name, (event) => {
  event.preventDefault();
  drop.classList.add('hot');
}));
['dragleave', 'drop'].forEach((name) => drop.addEventListener(name, (event) => {
  event.preventDefault();
  drop.classList.remove('hot');
}));
drop.addEventListener('drop', (event) => pick(event.dataTransfer.files[0]));

function pick(selected) {
  if (!selected) return;
  chosen = selected;
  drop.textContent = `${selected.name} (${Math.round(selected.size / 1024)} KB)`;
  go.disabled = false;
}

go.addEventListener('click', async () => {
  if (!chosen) return;
  err.textContent = '';
  result.hidden = true;
  go.disabled = true;
  status.textContent = 'Subiendo el zip…';
  const body = new FormData();
  body.append('zip', chosen);
  body.append('satellite', document.getElementById('sat').checked ? 'true' : 'false');
  body.append('language', document.getElementById('language').value);
  try {
    const job = await request('/jobs', { method: 'POST', body });
    await pollJob(job.poll_url);
  } catch (error) {
    err.textContent = error.message;
    status.textContent = '';
  } finally {
    go.disabled = false;
  }
});

async function pollJob(url) {
  const deadline = Date.now() + 30 * 60 * 1000;
  while (Date.now() < deadline) {
    const job = await request(url);
    if (job.status === 'succeeded') {
      renderResult(job.result);
      status.textContent = 'Listo.';
      return;
    }
    if (job.status === 'failed') {
      throw new Error(job.error || 'No se pudo procesar el zip.');
    }
    status.textContent = job.status === 'queued'
      ? 'En cola…'
      : 'Procesando… puede tardar si baja el satélite.';
    await new Promise((resolve) => setTimeout(resolve, 1000));
  }
  throw new Error('El procesamiento tardó demasiado. Revisá el estado del servidor.');
}

function renderResult(data) {
  result.hidden = false;
  document.getElementById('title').textContent = data.title;
  document.getElementById('summary').textContent = `${data.n_fields} lote(s) listos.`;
  const hasSplitTractorZips = Boolean(data.artifact_urls.aggps);
  const aggpsLink = document.getElementById('dlAgGPS');
  const shapefileLink = document.getElementById('dlShapefile');
  const imagesLink = document.getElementById('dlImages');
  aggpsLink.textContent = hasSplitTractorZips ? 'Descargar AgGPS' : 'Descargar USB Pro 700';
  aggpsLink.href = data.artifact_urls.aggps || data.artifact_urls.usb;
  shapefileLink.hidden = !hasSplitTractorZips;
  imagesLink.hidden = !data.artifact_urls.images;
  shapefileLink.href = data.artifact_urls.shapefile || '#';
  document.getElementById('dlPdf').href = data.artifact_urls.pdf;
  imagesLink.href = data.artifact_urls.images || '#';
  document.getElementById('dlAll').href = data.artifact_urls.bundle;
  const box = document.getElementById('fields');
  box.replaceChildren();
  (data.fields || []).forEach((field) => box.appendChild(renderField(field)));
}

function renderField(field) {
  const row = document.createElement('div');
  row.className = 'field';
  if (field.preview_url) {
    const image = document.createElement('img');
    image.src = field.preview_url;
    image.alt = `Mapa de ${field.field}`;
    image.loading = 'lazy';
    row.appendChild(image);
  } else {
    row.appendChild(document.createElement('div'));
  }

  const copy = document.createElement('div');
  copy.className = 'field-copy';
  const name = document.createElement('strong');
  name.textContent = `${field.client} / ${field.farm} / ${field.field}`;
  copy.append(name, document.createElement('br'), document.createTextNode('USB: '));
  const boundary = document.createElement('code');
  boundary.textContent = `${field.slug}_Bdy`;
  const taipas = document.createElement('code');
  taipas.textContent = `${field.slug}_Taipa`;
  copy.append(boundary, document.createTextNode(' + '), taipas, document.createElement('br'));
  const note = document.createElement('span');
  note.className = 'ok';
  note.textContent = field.note || '';
  copy.appendChild(note);
  row.appendChild(copy);
  return row;
}

checkSession();
