import './style.css';
import 'leaflet/dist/leaflet.css';
import L from 'leaflet';
import { iso1A2Code } from '@rapideditor/country-coder';

type Hike = {
  id: string;
  name: string;
  date: string | null;
  distance_km: number | null;
  elevation_gain_m: number | null;
  max_elevation_m: number | null;
  duration_h: number | null;
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
  manual_count?: number;
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

function truncateName(name: string, maxLength = 20): string {
  if (!name) return '';
  const normalized = Array.from(name);
  if (normalized.length <= maxLength) return name;
  return normalized.slice(0, maxLength - 1).join('') + '…';
}

function isoToFlag(iso: string | null): string | null {
  if (!iso || iso.length !== 2) return null;
  const chars = Array.from(iso.toUpperCase());
  return chars
    .map((char) => String.fromCodePoint(char.codePointAt(0)! + 127397))
    .join('');
}

function flagForHike(hike: Hike): string | null {
  const { lat, lng } = hike.location;
  if (lat == null || lng == null) return null;
  try {
    const iso = iso1A2Code([lng, lat]);
    return isoToFlag(iso || null);
  } catch {
    return null;
  }
}

async function fetchJSON<T>(url: string): Promise<T> {
  const response = await fetch(url, { cache: 'no-cache' });
  if (!response.ok) {
    throw new Error(`Failed to fetch ${url}`);
  }
  return (await response.json()) as T;
}

function formatNumber(value: number | null | undefined, decimals = 1): string {
  if (value == null || Number.isNaN(value)) {
    return '—';
  }
  return value.toLocaleString(undefined, {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
}

function formatWithUnit(value: number | null | undefined, decimals: number, unitLabel: string): string {
  const formatted = formatNumber(value, decimals);
  return formatted === '—' ? formatted : `${formatted} ${unitLabel}`;
}

function formatDate(value: string | null | undefined): string {
  if (!value) return '—';
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return value;
  }
  return parsed.toLocaleDateString();
}

function renderStats(hikes: Hike[]): void {
  const totalDistance = hikes.reduce((sum, hike) => sum + (hike.distance_km ?? 0), 0);
  const totalElevation = hikes.reduce((sum, hike) => sum + (hike.elevation_gain_m ?? 0), 0);
  const highestPoint = hikes.reduce((max, hike) => Math.max(max, hike.max_elevation_m ?? 0), 0);

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

function topByMetric(list: Hike[], metric: (hike: Hike) => number | null | undefined, limit = 5): Hike[] {
  return list
    .map((hike) => ({ hike, value: metric(hike) }))
    .filter(({ value }) => value != null && !Number.isNaN(value as number))
    .sort((a, b) => (b.value as number) - (a.value as number))
    .slice(0, limit)
    .map(({ hike }) => hike);
}

function renderTopLists(hikes: Hike[]): void {
  const topByDistance = topByMetric(hikes, (hike) => hike.distance_km);
  const topByGain = topByMetric(hikes, (hike) => hike.elevation_gain_m);
  const topByElevation = topByMetric(hikes, (hike) => hike.max_elevation_m);

  const makeList = (title: string, list: Hike[], unit: 'km' | 'm-gain' | 'm') => `
    <div class="top-card">
      <h3>${title}</h3>
      <ul>
        ${list
          .map((hike) => {
            const flag = flagForHike(hike);
            const value = unit === 'km'
              ? hike.distance_km
              : unit === 'm-gain'
              ? hike.elevation_gain_m
              : hike.max_elevation_m;
            const decimals = unit === 'km' ? 1 : 0;
            const unitLabel = unit === 'm-gain' ? 'm' : unit;
            const valueLabel = formatWithUnit(value, decimals, unitLabel);
            return `
              <li>
                <div>
                  <div class="flag-and-name">
                    ${flag ? `<span class="flag-pill">${flag}</span>` : ''}
                    <strong title="${hike.name}">${truncateName(hike.name)}</strong>
                  </div>
                  <span>${formatDate(hike.date)}</span>
                </div>
                <span class="value">${valueLabel}</span>
              </li>
            `;
          })
          .join('')}
      </ul>
    </div>
  `;

  const container = document.querySelector<HTMLDivElement>('#top-lists');
  if (!container) return;
  container.innerHTML = `
    ${makeList('🥾 Top distance', topByDistance, 'km')}
    ${makeList('📈 Top elevation gain', topByGain, 'm-gain')}
    ${makeList('🚩 Top max elevation', topByElevation, 'm')}
  `;
}

function attachMap(hikes: Hike[]): void {
  const currentMap = ensureMap();
  const validHikes = hikes.filter((hike) => hike.location.lat != null && hike.location.lng != null);
  if (validHikes.length === 0) {
    currentMap.setView([23.0, 10.0], 2.5);
    return;
  }

  const bounds = L.latLngBounds([]);

  validHikes.forEach((hike) => {
    if (hike.location.lat == null || hike.location.lng == null) return;
    const marker = L.marker([hike.location.lat, hike.location.lng], {
      icon: hikeIcon,
    }).addTo(currentMap);

    const polylineSection = hike.polyline
      ? '<p class="polyline-pill">Route ready</p>'
      : '<p class="polyline-pill muted">Route coming soon</p>';

    const photoFrame = `<div class="photo-placeholder">
      <span>Photo coming soon</span>
    </div>`;

    const flag = flagForHike(hike);

    marker.bindPopup(`
      <div class="popup-card">
        <header>
          <div class="title-block">
            ${flag ? `<span class="popup-flag">${flag}</span>` : ''}
            <div>
              <h3>${hike.name}</h3>
              <p>${formatDate(hike.date)}</p>
            </div>
          </div>
          ${polylineSection}
        </header>
        <ul class="popup-metrics">
          <li><span>Distance</span><strong>${formatWithUnit(hike.distance_km, 1, 'km')}</strong></li>
          <li><span>Elevation gain</span><strong>${formatWithUnit(hike.elevation_gain_m, 0, 'm')}</strong></li>
          <li><span>Max elevation</span><strong>${formatWithUnit(hike.max_elevation_m, 0, 'm')}</strong></li>
        </ul>
        ${photoFrame}
      </div>
    `);

    bounds.extend([hike.location.lat, hike.location.lng]);
  });

  if (!bounds.isValid()) {
    currentMap.setView([23.0, 10.0], 2.5);
  } else {
    currentMap.fitBounds(bounds.pad(0.25));
  }
}

function updateLastUpdated(meta: Meta | null): void {
  const lastUpdatedEl = document.querySelector<HTMLSpanElement>('#lastUpdated');
  if (!lastUpdatedEl || !meta) return;
  const date = new Date(meta.last_updated);
  const dateLabel = Number.isNaN(date.getTime()) ? meta.last_updated : date.toLocaleString();
  const manualInfo = meta.manual_count && meta.manual_count > 0 ? `${meta.source}, +${meta.manual_count} manual` : meta.source;
  lastUpdatedEl.textContent = `${dateLabel} (${manualInfo})`;
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
