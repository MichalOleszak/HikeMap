import './style.css';
import 'leaflet/dist/leaflet.css';
import L from 'leaflet';

type Hike = {
  id: string;
  name: string;
  date: string;
  distance_km: number;
  elevation_gain_m: number;
  max_elevation_m: number;
  duration_h: number;
  location: {
    lat: number | null;
    lng: number | null;
  };
  polyline: string | null;
  cover_photo: string | null;
};

type Meta = {
  last_updated: string;
  source: string;
};

const DATA_PATH = `${import.meta.env.BASE_URL}data/hikes.json`;
const META_PATH = `${import.meta.env.BASE_URL}data/meta.json`;

let map: L.Map | null = null;

const hikeIcon = L.divIcon({
  className: 'hike-marker',
  html: `<span class="marker-pulse"><span class="marker-core"></span></span>`,
  iconSize: [24, 24],
  iconAnchor: [12, 12],
});

function ensureMap(): L.Map {
  if (!map) {
    map = L.map('map', {
      zoomControl: false,
    });

    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      attribution: '&copy; OpenStreetMap contributors',
      minZoom: 2,
      maxZoom: 18,
    }).addTo(map);
  }
  return map;
}

async function fetchJSON<T>(url: string): Promise<T> {
  const response = await fetch(url, { cache: 'no-cache' });
  if (!response.ok) {
    throw new Error(`Failed to fetch ${url}`);
  }
  return (await response.json()) as T;
}

function formatNumber(value: number, decimals = 1): string {
  return value.toLocaleString(undefined, {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
}

function renderStats(hikes: Hike[]): void {
  const totalDistance = hikes.reduce((sum, hike) => sum + (hike.distance_km || 0), 0);
  const totalElevation = hikes.reduce((sum, hike) => sum + (hike.elevation_gain_m || 0), 0);
  const highestPoint = hikes.reduce((max, hike) => Math.max(max, hike.max_elevation_m || 0), 0);

  const statsEl = document.querySelector<HTMLDivElement>('#stats');
  if (!statsEl) return;

  statsEl.innerHTML = `
    <div class="stat-card">
      <span class="label">Total hikes</span>
      <strong>${hikes.length}</strong>
    </div>
    <div class="stat-card">
      <span class="label">Total distance</span>
      <strong>${formatNumber(totalDistance, 1)} km</strong>
    </div>
    <div class="stat-card">
      <span class="label">Total elevation gain</span>
      <strong>${formatNumber(totalElevation, 0)} m</strong>
    </div>
    <div class="stat-card">
      <span class="label">Highest point reached</span>
      <strong>${formatNumber(highestPoint, 0)} m</strong>
    </div>
  `;
}

function renderTopLists(hikes: Hike[]): void {
  const topByDistance = [...hikes]
    .sort((a, b) => b.distance_km - a.distance_km)
    .slice(0, 5);
  const topByGain = [...hikes]
    .sort((a, b) => b.elevation_gain_m - a.elevation_gain_m)
    .slice(0, 5);
  const topByElevation = [...hikes]
    .sort((a, b) => b.max_elevation_m - a.max_elevation_m)
    .slice(0, 5);

  const makeList = (title: string, list: Hike[], unit: string) => `
    <div class="top-card">
      <h3>${title}</h3>
      <ul>
        ${list
          .map(
            (hike) => `
              <li>
                <div>
                  <strong>${hike.name}</strong>
                  <span>${new Date(hike.date).toLocaleDateString()}</span>
                </div>
                <span class="value">${formatNumber(
                  unit === 'km' ? hike.distance_km : unit === 'm-gain' ? hike.elevation_gain_m : hike.max_elevation_m,
                  unit === 'km' ? 1 : 0
                )} ${unit === 'm-gain' ? 'm' : unit}</span>
              </li>
            `
          )
          .join('')}
      </ul>
    </div>
  `;

  const container = document.querySelector<HTMLDivElement>('#top-lists');
  if (!container) return;
  container.innerHTML = `
    ${makeList('Top distance', topByDistance, 'km')}
    ${makeList('Top elevation gain', topByGain, 'm-gain')}
    ${makeList('Top max elevation', topByElevation, 'm')}
  `;
}

function attachMap(hikes: Hike[]): void {
  const currentMap = ensureMap();
  const validHikes = hikes.filter((hike) => hike.location.lat && hike.location.lng);
  if (validHikes.length === 0) {
    currentMap.setView([46.0, 8.9], 5);
    return;
  }

  const bounds = L.latLngBounds([]);

  validHikes.forEach((hike) => {
    if (!hike.location.lat || !hike.location.lng) return;
    const marker = L.marker([hike.location.lat, hike.location.lng], {
      icon: hikeIcon,
    }).addTo(currentMap);

    const polylineSection = hike.polyline
      ? '<p class="polyline-pill">Route ready</p>'
      : '<p class="polyline-pill muted">Route coming soon</p>';

    const photoFrame = `<div class="photo-placeholder">
      <span>Photo coming soon</span>
    </div>`;

    marker.bindPopup(`
      <div class="popup">
        <h3>${hike.name}</h3>
        <p>${new Date(hike.date).toLocaleDateString()}</p>
        <ul>
          <li><strong>${formatNumber(hike.distance_km, 1)} km</strong> distance</li>
          <li><strong>${formatNumber(hike.elevation_gain_m, 0)} m</strong> elevation gain</li>
          <li><strong>${formatNumber(hike.max_elevation_m, 0)} m</strong> max elevation</li>
        </ul>
        ${photoFrame}
        ${polylineSection}
      </div>
    `);

    bounds.extend([hike.location.lat, hike.location.lng]);
  });

  if (!bounds.isValid()) {
    currentMap.setView([46.0, 8.9], 5);
  } else {
    currentMap.fitBounds(bounds.pad(0.25));
  }
}

function updateLastUpdated(meta: Meta | null): void {
  const lastUpdatedEl = document.querySelector<HTMLSpanElement>('#lastUpdated');
  if (!lastUpdatedEl || !meta) return;
  const date = new Date(meta.last_updated);
  lastUpdatedEl.textContent = `${date.toLocaleString()} (${meta.source})`;
}

async function init() {
  try {
    const [hikes, meta] = await Promise.all([
      fetchJSON<Hike[]>(DATA_PATH),
      fetchJSON<Meta>(META_PATH).catch(() => null),
    ]);

    if (!Array.isArray(hikes) || hikes.length === 0) {
      throw new Error('No hike data available');
    }

    attachMap(hikes);
    renderStats(hikes);
    renderTopLists(hikes);
    updateLastUpdated(meta);
  } catch (error) {
    console.error(error);
    const app = document.querySelector('#app');
    if (app) {
      app.innerHTML = '<p class="error">Failed to load hike data. Please try again later.</p>';
    }
  }
}

init();
