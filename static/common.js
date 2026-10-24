// Code shared by the pages: converting one song, ZIP downloads and song rows.
const LABELS = { downloading: 'Downloading', converting: 'Converting to MP3…' };

// Converts one YouTube link; calls onUpdate(label, percent|null) along the way, resolves to the download token
async function runConversion(url, onUpdate) {
  onUpdate('Starting…', 0);
  const res = await fetch('/start?url=' + encodeURIComponent(url));
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || 'Something went wrong.');
  while (true) {
    await new Promise(r => setTimeout(r, 500));
    const p = await (await fetch('/progress?job=' + encodeURIComponent(data.job))).json();
    if (p.state === 'error') throw new Error(p.error || 'Something went wrong.');
    if (p.state === 'done') return p.token;
    if (p.state === 'downloading') onUpdate('Downloading… ' + p.percent + '%', p.percent);
    else onUpdate(LABELS[p.state], null);
  }
}

function downloadLink(token, kind = 'MP3') {
  const a = document.createElement('a');
  a.className = 'dl';
  a.href = '/download?token=' + encodeURIComponent(token);
  a.textContent = '⬇ Download ' + kind;
  return a;
}

// One "Download MP3" button for a similar song; turns into a progress text, then a download link
function songDownloader(youtubeUrl) {
  const holder = document.createElement('span');
  const button = document.createElement('button');
  button.className = 'small';
  button.textContent = '⬇ Download MP3';
  button.addEventListener('click', async () => {
    button.disabled = true;
    try {
      const token = await runConversion(youtubeUrl, text => { button.textContent = text; });
      holder.replaceChildren(downloadLink(token));
    } catch (e) {
      button.disabled = false;
      button.textContent = '⬇ Try again';
      holder.title = e.message;
    }
  });
  holder.appendChild(button);
  return holder;
}
// "Download all as ZIP" for a list of songs: converts them on the server and offers one zip file
function zipButton(songs, label) {
  const holder = document.createElement('div');
  const button = document.createElement('button');
  button.style.background = '#2e7d32';
  button.textContent = label || '⬇ Download all ' + songs.length + ' as ZIP';
  const note = document.createElement('div');
  note.style.cssText = 'font-size:.85rem;color:#666;margin-top:.5rem';
  const bar = document.createElement('progress');
  bar.max = 100;
  bar.hidden = true;
  button.addEventListener('click', async () => {
    button.disabled = true;
    bar.hidden = false;
    bar.value = 0;
    note.textContent = 'Starting…';
    try {
      const res = await fetch('/zip/start', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ songs: songs.map(s => ({ name: s.name, url: s.url })) }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || 'Something went wrong.');
      while (true) {
        await new Promise(r => setTimeout(r, 1000));
        const p = await (await fetch('/progress?job=' + encodeURIComponent(data.job))).json();
        if (p.state === 'error') throw new Error(p.error || 'Something went wrong.');
        if (p.state === 'done') {
          holder.replaceChildren(downloadLink(p.token, 'ZIP'));
          if (p.failed.length) {
            const skipped = document.createElement('div');
            skipped.style.cssText = 'font-size:.85rem;color:#b00020;margin-top:.5rem';
            skipped.textContent = 'Could not download: ' + p.failed.join(', ');
            holder.appendChild(skipped);
          }
          return;
        }
        bar.value = p.total ? p.done / p.total * 100 : 0;
        note.textContent = p.state === 'zipping' ? 'Making the zip file…' : 'Converted ' + p.done + ' of ' + p.total + '…';
      }
    } catch (e) {
      button.disabled = false;
      bar.hidden = true;
      note.textContent = e.message;
    }
  });
  holder.append(button, document.createElement('br'), bar, note);
  return holder;
}

// One list item: song name, YouTube link and Download MP3 button (or a note when no clean link was found)
function songRow(song) {
  const li = document.createElement('li');
  li.textContent = song.name + ' ';
  if (song.url) {
    const a = document.createElement('a');
    a.href = song.url;
    a.target = '_blank';
    a.rel = 'noopener';
    a.textContent = '▶ YouTube';
    li.appendChild(a);
    li.appendChild(document.createTextNode(' '));
    li.appendChild(songDownloader(song.url));
  } else {
    const none = document.createElement('span');
    none.style.color = '#888';
    none.textContent = '(no clean audio found)';
    li.appendChild(none);
  }
  return li;
}

// Removes repeats from a list of {name, url} songs: the same video, or the same song title and artist
// (versions like "- Radio Edit" or "(feat. X)" count as the same song). Keeps the first of each.
function uniqueSongs(songs) {
  const seen = new Set();
  return songs.filter(song => {
    const [title, artist = ''] = song.name.replace(/[\u2018\u2019]/g, "'").split(' \u2014 ');
    const base = title.split(/\s+-\s+|\s*[(\[]/)[0].trim().toLowerCase();
    const video = (song.url.match(/[?&]v=([^&]+)/) || [])[1] || song.url;
    const keys = ['v:' + video, 's:' + base + '|' + artist.trim().toLowerCase()];
    if (keys.some(k => seen.has(k))) return false;
    keys.forEach(k => seen.add(k));
    return true;
  });
}
