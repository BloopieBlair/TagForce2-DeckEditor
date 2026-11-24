'use strict';

/* ==================== CONSTANTS & STATE ==================== */
const CARDS_PER_PAGE = 40;
const MAX_HISTORY = 100;
const MAX_MAIN = 80;
const MAX_SIDE = 15;
const MAX_EXTRA = 30;
const STATIC_STORAGE_KEY = 'duelist_hub_static_deck_v1';

const FRAME_LABELS = {
    normal: 'Normal Monster',
    effect: 'Effect Monster',
    fusion: 'Fusion Monster',
    ritual: 'Ritual Monster',
    spell: 'Spell Card',
    trap: 'Trap Card',
    anime: 'Anime Exclusive',
    token: 'Token'
};

const FRAME_COLORS = {
    normal: '#c9a66b',
    effect: '#d47a3e',
    fusion: '#8b5cf6',
    ritual: '#3b82f6',
    spell: '#10b981',
    trap: '#ec4899',
    anime: '#6366f1',
    token: '#94a3b8'
};

const ATTR_COLORS = {
    LIGHT: '#facc15',
    DARK: '#a855f7',
    EARTH: '#d97706',
    WATER: '#38bdf8',
    FIRE: '#ef4444',
    WIND: '#34d399',
    DIVINE: '#fbbf24'
};

const SUBTYPE_SHORT = {
    'Quick-Play': 'QP',
    'Continuous': 'CNT',
    'Field': 'FLD',
    'Equip': 'EQP',
    'Ritual': 'RIT',
    'Counter': 'CTR',
    'Normal': 'NRM'
};

const state = {
    cardsDb: [],
    cardsByIndex: new Map(),
    cardsByPasscode: new Map(),
    filteredCards: [],
    currentPage: 1,

    playerDeck: {
        name: 'Cyber-Dragon Demo Deck',
        main: [],
        side: [],
        extra: []
    },
    isDirty: false,

    deckHistory: [],
    historyIndex: -1,

    hoveredCard: null,
    pinnedCard: null,

    backendAvailable: false,
    serverStatus: {
        mode: 'static',
        save_path: null,
        region: null,
        encrypted: false,
        deck_offset: null,
        backups: [],
        art_cache_enabled: false,
        art_dir_configured: false,
        text_cache_count: 0,
        auto_unlock_default: true
    },
    autoUnlock: true,
    cardDescriptions: {},
    failedArtCache: new Set(),

    handDeckPool: [],
    currentHand: [],

    confirmCallback: null,
    searchTimer: null,
    nameHistoryTimer: null
};

/* ==================== SVG RACE / TYPE EMBLEMS ==================== */
const SVG_PATHS = {
    machine: '<circle cx="12" cy="12" r="3.2" stroke="currentColor" stroke-width="1.8"/><path d="M12 2.5v3m0 13v3m9.5-9.5h-3m-13 0h-3m15.7-6.7-2.1 2.1M7.4 16.6l-2.1 2.1m13.4 0-2.1-2.1M7.4 7.4 5.3 5.3" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/>',
    dragon: '<path d="M4 18c2-5 4-9 8-12 2 2 5 2 8 1-1 3-3 5-5 6 2 1 3 3 3 5-4-1-6 0-8 2-1-2-3-3-6-2Z" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round"/><circle cx="13.5" cy="9.5" r="1" fill="currentColor"/>',
    spellcaster: '<polygon points="12,2.5 14.7,8.7 21.5,9.3 16.3,13.7 17.9,20.5 12,16.9 6.1,20.5 7.7,13.7 2.5,9.3 9.3,8.7" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"/>',
    warrior: '<path d="M5 19 18 6m-5-1 6-1-1 6M6 14l4 4m-6 1 2-2" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>',
    fiend: '<path d="M5 6c1 3 3 5 7 5s6-2 7-5c0 7-3 13-7 15-4-2-7-8-7-15Z" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round"/><circle cx="9.5" cy="12" r="1" fill="currentColor"/><circle cx="14.5" cy="12" r="1" fill="currentColor"/>',
    fairy: '<path d="M12 4v16M4 10c3-2 6-1 8 2 2-3 5-4 8-2-1 4-4 6-8 6s-7-2-8-6Z" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round"/>',
    beast: '<path d="M6 17c0-5 2-9 6-11 4 2 6 6 6 11-2 1-4 2-6 2s-4-1-6-2Z" stroke="currentColor" stroke-width="1.7"/><path d="M8 7 6 4m10 3 2-3M9.5 12.5h.01M14.5 12.5h.01" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/>',
    zombie: '<circle cx="12" cy="10" r="6" stroke="currentColor" stroke-width="1.7"/><path d="M9 16v3m3-3v3m3-3v3M9.5 10h.01M14.5 10h.01" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/>',
    aqua: '<path d="M12 3s6 6.8 6 11a6 6 0 1 1-12 0c0-4.2 6-11 6-11Z" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round"/>',
    pyro: '<path d="M12 3c3 4 6 6.5 6 11a6 6 0 1 1-12 0c0-2.8 1.5-5.3 3-7 0 2 1.2 3 2.5 3C11.5 7.5 11.5 5 12 3Z" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round"/>',
    thunder: '<polygon points="13,2.5 5.5,13 11.5,13 10.5,21.5 18.5,10.5 12.5,10.5" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round"/>',
    plant: '<path d="M12 20V10m0 0C12 6 8 4 4 5c0 4 3 7 8 5Zm0 0c0-4 4-6 8-5 0 4-3 7-8 5Z" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round"/>',
    rock: '<polygon points="12,3 20,8 18,18 12,21 6,18 4,8" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round"/>',
    winged: '<path d="M3 14c4-6 9-8 18-8-3 4-5 7-9 9l-2 4-2-4-5-1Z" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round"/>',
    spell: '<circle cx="12" cy="12" r="8" stroke="currentColor" stroke-width="1.6"/><polygon points="12,5.5 17.5,15.5 6.5,15.5" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/><circle cx="12" cy="12" r="2" fill="currentColor"/>',
    trap: '<path d="M2.5 12s3.8-6 9.5-6 9.5 6 9.5 6-3.8 6-9.5 6-9.5-6-9.5-6Z" stroke="currentColor" stroke-width="1.7"/><circle cx="12" cy="12" r="2.8" stroke="currentColor" stroke-width="1.7"/>',
    anime: '<polygon points="12,2.5 21,12 12,21.5 3,12" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round"/><polygon points="12,7 16.5,12 12,17 7.5,12" stroke="currentColor" stroke-width="1.4"/>',
    default: '<polygon points="12,3 20,12 12,21 4,12" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round"/><circle cx="12" cy="12" r="2.5" stroke="currentColor" stroke-width="1.5"/>'
};

function getEmblemKey(card) {
    const frame = getCardFrame(card);
    if (frame === 'anime') return 'anime';
    if (frame === 'spell') return 'spell';
    if (frame === 'trap') return 'trap';
    const race = (card.race || '').toLowerCase();
    if (race.includes('machine')) return 'machine';
    if (race.includes('dragon') || race.includes('dinosaur') || race.includes('reptile') || race.includes('sea serpent')) return 'dragon';
    if (race.includes('spellcaster') || race.includes('divine')) return 'spellcaster';
    if (race.includes('warrior')) return 'warrior';
    if (race.includes('fiend')) return 'fiend';
    if (race.includes('fairy')) return 'fairy';
    if (race.includes('beast') && !race.includes('winged')) return 'beast';
    if (race.includes('winged')) return 'winged';
    if (race.includes('zombie')) return 'zombie';
    if (race.includes('aqua') || race.includes('fish')) return 'aqua';
    if (race.includes('pyro')) return 'pyro';
    if (race.includes('thunder')) return 'thunder';
    if (race.includes('plant') || race.includes('insect')) return 'plant';
    if (race.includes('rock')) return 'rock';
    return 'default';
}

function createEmblemSvg(card, className) {
    const ns = 'http://www.w3.org/2000/svg';
    const svg = document.createElementNS(ns, 'svg');
    svg.setAttribute('viewBox', '0 0 24 24');
    svg.setAttribute('fill', 'none');
    svg.setAttribute('aria-hidden', 'true');
    if (className) svg.setAttribute('class', className);
    svg.innerHTML = SVG_PATHS[getEmblemKey(card)] || SVG_PATHS.default;
    return svg;
}

/* ==================== CARD DATA HELPERS ==================== */
function getCardFrame(card) {
    if (!card) return 'effect';
    if (card.is_anime) return 'anime';
    const ft = (card.frame_type || '').toLowerCase();
    if (FRAME_LABELS[ft]) return ft;
    const t = (card.type || '').toLowerCase();
    if (t.includes('fusion')) return 'fusion';
    if (t.includes('ritual') && t.includes('monster')) return 'ritual';
    if (t.includes('normal') && t.includes('monster')) return 'normal';
    if (t.includes('monster')) return 'effect';
    if (t.includes('spell')) return 'spell';
    if (t.includes('trap')) return 'trap';
    return 'anime';
}

function isMonsterCard(card) {
    const frame = getCardFrame(card);
    return frame === 'normal' || frame === 'effect' || frame === 'fusion' || frame === 'ritual' || frame === 'token';
}

function isFusionCard(card) {
    const frame = getCardFrame(card);
    return frame === 'fusion' || (card.type || '').toLowerCase().includes('fusion');
}

function formatStat(val) {
    if (val === null || val === undefined || val < 0) return '?';
    return String(val);
}

function isValidArtPasscode(passcode) {
    if (!passcode || typeof passcode !== 'string') return false;
    if (!/^\d+$/.test(passcode)) return false;
    return parseInt(passcode, 10) > 0;
}

function canLoadLocalArt(card) {
    if (!card || card.is_anime) return false;
    if (!state.backendAvailable) return false;
    if (!state.serverStatus.art_cache_enabled && !state.serverStatus.art_dir_configured) return false;
    if (!isValidArtPasscode(card.passcode)) return false;
    if (state.failedArtCache.has(card.passcode)) return false;
    return true;
}

function attachOptionalLocalArt(container, card, size) {
    if (!canLoadLocalArt(card)) return;
    const img = document.createElement('img');
    img.className = 'local-art-overlay';
    img.alt = card.name;
    img.decoding = 'async';
    if (size === 'small') img.loading = 'lazy';
    img.src = `/api/card_image/${encodeURIComponent(card.passcode)}?size=${size}`;
    img.addEventListener('load', () => {
        img.classList.add('loaded');
    });
    img.addEventListener('error', () => {
        state.failedArtCache.add(card.passcode);
        img.remove();
    });
    container.appendChild(img);
}

function getCardDescription(card) {
    if (!card) return '';
    const pc = card.passcode || '';
    if (pc && state.cardDescriptions[pc]) return state.cardDescriptions[pc];
    const stripped = isValidArtPasscode(pc) ? String(parseInt(pc, 10)) : '';
    if (stripped && state.cardDescriptions[stripped]) return state.cardDescriptions[stripped];
    return '';
}

function buildFactualSummary(card) {
    const parts = [];
    if (card.race && card.race !== 'Unknown') parts.push(card.race);
    parts.push(card.type || FRAME_LABELS[getCardFrame(card)] || 'Card');
    if (card.attribute) parts.push(card.attribute);
    if (card.level) parts.push(`Level ${card.level}`);
    if (isMonsterCard(card)) {
        parts.push(`ATK ${formatStat(card.atk)} / DEF ${formatStat(card.def)}`);
    }
    if (card.is_anime) {
        parts.push('Tag Force 2 Anime-Exclusive');
    }
    return parts.join(' \u00b7 ');
}

function resolveCardEntry(entry) {
    if (typeof entry === 'number') {
        return state.cardsByIndex.get(entry) || null;
    }
    if (entry && typeof entry === 'object') {
        if (typeof entry.game_index === 'number' && state.cardsByIndex.has(entry.game_index)) {
            return state.cardsByIndex.get(entry.game_index);
        }
        if (entry.name) return entry;
    }
    return null;
}

function countCopiesInDeck(cardName) {
    let count = 0;
    for (const c of state.playerDeck.main) if (c.name === cardName) count++;
    for (const c of state.playerDeck.extra) if (c.name === cardName) count++;
    for (const c of state.playerDeck.side) if (c.name === cardName) count++;
    return count;
}

function getDeckCopyMap() {
    const map = new Map();
    const add = (c) => map.set(c.name, (map.get(c.name) || 0) + 1);
    state.playerDeck.main.forEach(add);
    state.playerDeck.extra.forEach(add);
    state.playerDeck.side.forEach(add);
    return map;
}

/* ==================== TOASTS & CONFIRM MODAL ==================== */
function showToast(message, type = 'info', actionLabel = null, actionFn = null) {
    const container = document.getElementById('toast-container');
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;

    const text = document.createElement('span');
    text.textContent = message;
    toast.appendChild(text);

    if (actionLabel && typeof actionFn === 'function') {
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'toast-action';
        btn.textContent = actionLabel;
        btn.addEventListener('click', () => {
            actionFn();
            toast.remove();
        });
        toast.appendChild(btn);
    }

    container.appendChild(toast);
    while (container.children.length > 4) {
        container.firstChild.remove();
    }

    setTimeout(() => {
        if (toast.isConnected) toast.remove();
    }, actionLabel ? 4800 : 3200);
}

function openConfirmModal(title, message, confirmLabel, onConfirm) {
    document.getElementById('modal-confirm-title').textContent = title;
    document.getElementById('modal-confirm-message').textContent = message;
    document.getElementById('btn-confirm-ok').textContent = confirmLabel || 'Confirm';
    state.confirmCallback = onConfirm;
    openModal('modal-confirm');
}

function openModal(id) {
    const el = document.getElementById(id);
    if (!el) return;
    el.hidden = false;
    const focusTarget = el.querySelector('button:not(:disabled), input:not(:disabled), textarea:not(:disabled)');
    if (focusTarget) focusTarget.focus();
}

function closeModal(id) {
    const el = document.getElementById(id);
    if (el) el.hidden = true;
    if (id === 'modal-confirm') state.confirmCallback = null;
}

function closeAllModals() {
    document.querySelectorAll('.modal-backdrop').forEach(m => {
        m.hidden = true;
    });
    state.confirmCallback = null;
}

function anyModalOpen() {
    return Array.from(document.querySelectorAll('.modal-backdrop')).some(m => !m.hidden);
}

/* ==================== HISTORY & DIRTY STATE ==================== */
function pushHistory(markDirty = true) {
    if (state.historyIndex < state.deckHistory.length - 1) {
        state.deckHistory = state.deckHistory.slice(0, state.historyIndex + 1);
    }
    state.deckHistory.push({
        name: state.playerDeck.name,
        main: [...state.playerDeck.main],
        side: [...state.playerDeck.side],
        extra: [...state.playerDeck.extra]
    });
    if (state.deckHistory.length > MAX_HISTORY) {
        state.deckHistory.shift();
    }
    state.historyIndex = state.deckHistory.length - 1;
    if (markDirty) setDirty(true);
    updateHistoryButtons();
}

function setDirty(dirty) {
    state.isDirty = dirty;
    document.getElementById('dirty-dot').hidden = !dirty;
}

function updateHistoryButtons() {
    document.getElementById('btn-undo').disabled = state.historyIndex <= 0;
    document.getElementById('btn-redo').disabled = state.historyIndex >= state.deckHistory.length - 1;
}

function restoreHistoryEntry(entry) {
    state.playerDeck.name = entry.name;
    state.playerDeck.main = [...entry.main];
    state.playerDeck.side = [...entry.side];
    state.playerDeck.extra = [...entry.extra];
    document.getElementById('deck-name-input').value = state.playerDeck.name;
    setDirty(true);
    updateHistoryButtons();
    renderDeck();
    renderDatabaseResults();
    refreshInspectorCopyCount();
}

function undo() {
    if (state.historyIndex <= 0) return;
    state.historyIndex--;
    restoreHistoryEntry(state.deckHistory[state.historyIndex]);
}

function redo() {
    if (state.historyIndex >= state.deckHistory.length - 1) return;
    state.historyIndex++;
    restoreHistoryEntry(state.deckHistory[state.historyIndex]);
}

/* ==================== PROCEDURAL CARD BUILDERS ==================== */
function buildLargeProceduralCard(card) {
    const frame = getCardFrame(card);
    const el = document.createElement('div');
    el.className = 'pcard-lg';
    el.dataset.frame = frame;

    // Header bar
    const header = document.createElement('div');
    header.className = 'pcard-lg-header';

    const nameSpan = document.createElement('span');
    nameSpan.className = 'pcard-lg-name';
    nameSpan.textContent = card.name;
    header.appendChild(nameSpan);

    const orb = document.createElement('span');
    let orbClass = 'attr-ANIME';
    let orbText = 'A';
    if (card.attribute && ATTR_COLORS[card.attribute]) {
        orbClass = `attr-${card.attribute}`;
        orbText = card.attribute.slice(0, 2);
    } else if (frame === 'spell') {
        orbClass = 'attr-SPELL';
        orbText = 'SP';
    } else if (frame === 'trap') {
        orbClass = 'attr-TRAP';
        orbText = 'TR';
    }
    orb.className = `attr-orb ${orbClass}`;
    orb.textContent = orbText;
    orb.title = card.attribute || FRAME_LABELS[frame];
    header.appendChild(orb);
    el.appendChild(header);

    // Subbar (Level stars or Spell/Trap subtype)
    const subbar = document.createElement('div');
    subbar.className = 'pcard-lg-subbar';
    if (card.level) {
        const stars = document.createElement('span');
        stars.className = 'level-stars';
        stars.textContent = '\u2605'.repeat(Math.min(card.level, 12));
        stars.title = `Level ${card.level}`;
        subbar.appendChild(stars);
    } else {
        const stLabel = document.createElement('span');
        stLabel.className = 'st-subtype-label';
        const raceText = card.race && card.race !== 'Unknown' ? `${card.race} ` : '';
        stLabel.textContent = frame === 'anime' ? '[ANIME CARD]' : `[${raceText}${frame.toUpperCase()}]`;
        subbar.appendChild(stLabel);
    }
    el.appendChild(subbar);

    // Artwork area with crisp geometric SVG emblem
    const art = document.createElement('div');
    art.className = 'pcard-lg-art';
    art.appendChild(createEmblemSvg(card, 'pcard-lg-emblem'));

    const emblemLabel = document.createElement('span');
    emblemLabel.className = 'pcard-lg-emblem-label';
    emblemLabel.textContent = card.race && card.race !== 'Unknown'
        ? card.race
        : FRAME_LABELS[frame];
    art.appendChild(emblemLabel);
    el.appendChild(art);

    // Footer bar
    const footer = document.createElement('div');
    footer.className = 'pcard-lg-footer';

    const typeLine = document.createElement('div');
    typeLine.className = 'pcard-lg-type-line';
    const racePrefix = card.race && card.race !== 'Unknown' ? `${card.race} / ` : '';
    typeLine.textContent = `[${racePrefix}${card.type || FRAME_LABELS[frame]}]`;
    footer.appendChild(typeLine);

    if (isMonsterCard(card)) {
        const atkDef = document.createElement('div');
        atkDef.className = 'pcard-lg-atkdef';
        atkDef.textContent = `ATK/${formatStat(card.atk)}  DEF/${formatStat(card.def)}`;
        footer.appendChild(atkDef);
    }

    el.appendChild(footer);

    // Optional opt-in local art overlay (zero hotlinking)
    attachOptionalLocalArt(el, card, 'full');
    return el;
}

function buildDeckTileElement(card, index, targetDeck, interactive = true) {
    const frame = getCardFrame(card);
    const tile = document.createElement('div');
    tile.className = 'deck-card-tile';
    tile.dataset.frame = frame;
    tile.setAttribute('role', 'listitem');
    tile.tabIndex = 0;
    tile.setAttribute('aria-label', `${card.name}, ${card.type || FRAME_LABELS[frame]}`);

    if (state.pinnedCard && state.pinnedCard.game_index === card.game_index && interactive) {
        tile.classList.add('is-pinned');
    }

    // Top micro bar
    const top = document.createElement('div');
    top.className = 'tile-top';

    const dot = document.createElement('span');
    dot.className = 'tile-attr-dot';
    dot.style.backgroundColor = card.attribute && ATTR_COLORS[card.attribute]
        ? ATTR_COLORS[card.attribute]
        : (FRAME_COLORS[frame] || '#8b5cf6');
    top.appendChild(dot);

    if (card.level) {
        const lvl = document.createElement('span');
        lvl.className = 'tile-lvl';
        lvl.textContent = `\u2605${card.level}`;
        top.appendChild(lvl);
    } else {
        const tag = document.createElement('span');
        tag.className = 'tile-st-tag';
        tag.textContent = SUBTYPE_SHORT[card.race] || (frame === 'spell' ? 'SPL' : frame === 'trap' ? 'TRP' : 'ANM');
        top.appendChild(tag);
    }
    tile.appendChild(top);

    // Center emblem + name
    const center = document.createElement('div');
    center.className = 'tile-center';
    center.appendChild(createEmblemSvg(card, 'tile-bg-emblem'));

    const name = document.createElement('span');
    name.className = 'tile-name';
    name.textContent = card.name;
    center.appendChild(name);
    tile.appendChild(center);

    // Bottom stats / tag
    const bottom = document.createElement('div');
    bottom.className = 'tile-bottom';
    if (isMonsterCard(card)) {
        bottom.textContent = `${formatStat(card.atk)}/${formatStat(card.def)}`;
    } else if (frame === 'spell') {
        bottom.textContent = card.race && card.race !== 'Normal' && card.race !== 'Unknown' ? card.race : 'SPELL';
    } else if (frame === 'trap') {
        bottom.textContent = card.race && card.race !== 'Normal' && card.race !== 'Unknown' ? card.race : 'TRAP';
    } else {
        bottom.textContent = 'ANIME';
    }
    tile.appendChild(bottom);

    // Optional local art overlay
    attachOptionalLocalArt(tile, card, 'small');

    if (interactive) {
        const removeBtn = document.createElement('button');
        removeBtn.type = 'button';
        removeBtn.className = 'tile-remove-btn';
        removeBtn.innerHTML = '&times;';
        removeBtn.title = `Remove ${card.name}`;
        removeBtn.setAttribute('aria-label', `Remove ${card.name} from ${targetDeck} deck`);
        removeBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            removeCard(index, targetDeck);
        });
        tile.appendChild(removeBtn);

        tile.addEventListener('mouseenter', () => previewCard(card));
        tile.addEventListener('focus', () => previewCard(card));
        tile.addEventListener('click', () => togglePinCard(card));
        tile.addEventListener('contextmenu', (e) => {
            e.preventDefault();
            removeCard(index, targetDeck);
        });
        tile.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                togglePinCard(card);
            } else if (e.key === 'Delete' || e.key === 'Backspace') {
                e.preventDefault();
                removeCard(index, targetDeck);
            }
        });
    } else {
        tile.addEventListener('click', () => pinCard(card));
        tile.addEventListener('mouseenter', () => previewCard(card));
    }

    return tile;
}

function buildSearchThumbnail(card) {
    const frame = getCardFrame(card);
    const thumb = document.createElement('div');
    thumb.className = 'search-thumb';
    thumb.dataset.frame = frame;

    const dot = document.createElement('span');
    dot.className = 'tile-attr-dot';
    dot.style.backgroundColor = card.attribute && ATTR_COLORS[card.attribute]
        ? ATTR_COLORS[card.attribute]
        : (FRAME_COLORS[frame] || '#8b5cf6');
    thumb.appendChild(dot);

    thumb.appendChild(createEmblemSvg(card, 'search-thumb-emblem'));

    const tag = document.createElement('span');
    tag.className = 'search-thumb-tag';
    tag.textContent = card.level ? `\u2605${card.level}` : frame.slice(0, 3).toUpperCase();
    thumb.appendChild(tag);

    attachOptionalLocalArt(thumb, card, 'small');
    return thumb;
}

/* ==================== INSPECTOR (HOVER + CLICK-TO-PIN) ==================== */
function getActiveInspectedCard() {
    return state.pinnedCard || state.hoveredCard;
}

function previewCard(card) {
    if (!card) return;
    state.hoveredCard = card;
    if (!state.pinnedCard) {
        renderInspector(card);
    }
}

function pinCard(card) {
    if (!card) return;
    state.pinnedCard = card;
    updatePinBadge();
    renderInspector(card);
    updatePinnedTileHighlight();
}

function togglePinCard(card) {
    if (state.pinnedCard && state.pinnedCard.game_index === card.game_index) {
        unpinCard();
    } else {
        pinCard(card);
    }
}

function unpinCard() {
    state.pinnedCard = null;
    updatePinBadge();
    updatePinnedTileHighlight();
    if (state.hoveredCard) {
        renderInspector(state.hoveredCard);
    }
}

function updatePinBadge() {
    const badge = document.getElementById('pin-badge');
    const text = document.getElementById('pin-badge-text');
    if (state.pinnedCard) {
        badge.classList.add('pinned');
        badge.setAttribute('aria-pressed', 'true');
        text.textContent = 'Pinned \u00d7';
        badge.title = 'Click to unpin (Esc)';
    } else {
        badge.classList.remove('pinned');
        badge.setAttribute('aria-pressed', 'false');
        text.textContent = 'Hover preview';
        badge.title = 'Click any card to pin it in the inspector';
    }
}

function updatePinnedTileHighlight() {
    document.querySelectorAll('.deck-card-tile.is-pinned').forEach(el => el.classList.remove('is-pinned'));
    if (!state.pinnedCard) return;
    // Highlight matching tiles on next full render or directly
    renderDeckHighlights();
}

function renderDeckHighlights() {
    const pinnedIdx = state.pinnedCard ? state.pinnedCard.game_index : null;
    const grids = [
        { el: document.getElementById('main-deck-grid'), list: state.playerDeck.main },
        { el: document.getElementById('extra-deck-grid'), list: state.playerDeck.extra },
        { el: document.getElementById('side-deck-grid'), list: state.playerDeck.side }
    ];
    for (const g of grids) {
        const tiles = g.el.querySelectorAll('.deck-card-tile');
        tiles.forEach((tile, i) => {
            const card = g.list[i];
            tile.classList.toggle('is-pinned', Boolean(card && pinnedIdx !== null && card.game_index === pinnedIdx));
        });
    }
}

function refreshInspectorCopyCount() {
    const card = getActiveInspectedCard();
    if (!card) return;
    const copies = countCopiesInDeck(card.name);
    const el = document.getElementById('inspector-copy-count');
    el.textContent = `${copies} / 3 in deck`;
    el.classList.toggle('maxed', copies >= 3);

    const addMainBtn = document.getElementById('btn-inspector-add-main');
    const addSideBtn = document.getElementById('btn-inspector-add-side');
    addMainBtn.disabled = copies >= 3;
    addSideBtn.disabled = copies >= 3;
}

function renderInspector(card) {
    if (!card) return;
    const frame = getCardFrame(card);

    document.getElementById('inspector-empty').hidden = true;
    const host = document.getElementById('inspector-card-host');
    host.hidden = false;
    host.innerHTML = '';
    host.appendChild(buildLargeProceduralCard(card));

    document.getElementById('card-details-info').hidden = false;

    // Quick add button adapts for Fusion vs Main
    const addMainBtn = document.getElementById('btn-inspector-add-main');
    if (isFusionCard(card)) {
        addMainBtn.textContent = '+ Extra';
        addMainBtn.className = 'btn btn-xs btn-add-extra';
    } else {
        addMainBtn.textContent = '+ Main';
        addMainBtn.className = 'btn btn-xs btn-add-primary';
    }
    refreshInspectorCopyCount();

    // Badges
    const frameBadge = document.getElementById('detail-frame');
    frameBadge.textContent = FRAME_LABELS[frame] || card.type || 'Card';
    frameBadge.className = `badge frame-${frame}`;

    const raceBadge = document.getElementById('detail-race');
    if (card.race && card.race !== 'Unknown') {
        raceBadge.textContent = card.race;
        raceBadge.hidden = false;
    } else {
        raceBadge.hidden = true;
    }

    const attrBadge = document.getElementById('detail-attribute');
    if (card.attribute) {
        attrBadge.textContent = card.attribute;
        attrBadge.hidden = false;
    } else {
        attrBadge.hidden = true;
    }

    const lvlBadge = document.getElementById('detail-level');
    if (card.level) {
        lvlBadge.textContent = `\u2605 ${card.level}`;
        lvlBadge.hidden = false;
    } else {
        lvlBadge.hidden = true;
    }

    document.getElementById('detail-anime').hidden = !card.is_anime;

    // Stats (fixes -1 -> ?)
    const statsRow = document.getElementById('detail-stats');
    if (isMonsterCard(card)) {
        statsRow.hidden = false;
        document.getElementById('detail-atk').textContent = formatStat(card.atk);
        document.getElementById('detail-def').textContent = formatStat(card.def);
    } else {
        statsRow.hidden = true;
    }

    // Description or factual summary + local sync prompt
    const descEl = document.getElementById('detail-desc');
    const hintBtn = document.getElementById('btn-desc-sync-hint');
    const syncedDesc = getCardDescription(card);
    if (syncedDesc) {
        descEl.textContent = syncedDesc;
        hintBtn.hidden = true;
    } else {
        descEl.textContent = buildFactualSummary(card);
        hintBtn.hidden = card.is_anime || !state.backendAvailable;
    }

    document.getElementById('detail-passcode').textContent = card.passcode || '00000000';
    document.getElementById('detail-game-index').textContent = `#${card.game_index}`;
}

/* ==================== DECK MUTATIONS ==================== */
function addCard(card, targetDeck) {
    if (!card) return;
    const isFusion = isFusionCard(card);

    if (targetDeck === 'main' && isFusion) {
        targetDeck = 'extra';
    } else if (targetDeck === 'extra' && !isFusion) {
        showToast('Only Fusion Monsters can be added to the Extra Deck.', 'warning');
        return;
    }

    if (targetDeck === 'main' && state.playerDeck.main.length >= MAX_MAIN) {
        showToast(`Main Deck cannot exceed ${MAX_MAIN} cards.`, 'warning');
        return;
    }
    if (targetDeck === 'side' && state.playerDeck.side.length >= MAX_SIDE) {
        showToast(`Side Deck cannot exceed ${MAX_SIDE} cards.`, 'warning');
        return;
    }
    if (targetDeck === 'extra' && state.playerDeck.extra.length >= MAX_EXTRA) {
        showToast(`Extra Deck cannot exceed ${MAX_EXTRA} cards.`, 'warning');
        return;
    }

    if (countCopiesInDeck(card.name) >= 3) {
        showToast(`Maximum 3 copies of "${card.name}" allowed across Main, Extra, and Side.`, 'warning');
        return;
    }

    state.playerDeck[targetDeck].push(card);
    pushHistory(true);
    renderDeck();
    renderDatabaseResults();
    refreshInspectorCopyCount();
}

function removeCard(index, targetDeck) {
    const list = state.playerDeck[targetDeck];
    if (!list || index < 0 || index >= list.length) return;
    const [removed] = list.splice(index, 1);
    pushHistory(true);
    renderDeck();
    renderDatabaseResults();
    refreshInspectorCopyCount();
    showToast(`Removed "${removed.name}"`, 'info', 'Undo', () => undo());
}

function requestClearDeck() {
    const total = state.playerDeck.main.length + state.playerDeck.extra.length + state.playerDeck.side.length;
    if (total === 0) {
        showToast('Deck is already empty.', 'info');
        return;
    }
    openConfirmModal(
        'Clear Entire Deck?',
        `This removes all ${total} cards from Main, Extra, and Side Decks. You can still revert with Undo.`,
        'Clear Deck',
        () => {
            state.playerDeck.main = [];
            state.playerDeck.extra = [];
            state.playerDeck.side = [];
            pushHistory(true);
            renderDeck();
            renderDatabaseResults();
            refreshInspectorCopyCount();
            showToast('Deck cleared.', 'info', 'Undo', () => undo());
        }
    );
}

function shuffleDeck() {
    if (state.playerDeck.main.length <= 1) return;
    const arr = [...state.playerDeck.main];
    for (let i = arr.length - 1; i > 0; i--) {
        const j = Math.floor(Math.random() * (i + 1));
        [arr[i], arr[j]] = [arr[j], arr[i]];
    }
    state.playerDeck.main = arr;
    pushHistory(true);
    renderDeck();
    showToast('Main Deck shuffled.', 'info');
}

function sortDeck() {
    const frameRank = { normal: 1, effect: 2, ritual: 3, fusion: 4, spell: 5, trap: 6, anime: 7, token: 8 };
    const cmp = (a, b) => {
        const fa = frameRank[getCardFrame(a)] || 9;
        const fb = frameRank[getCardFrame(b)] || 9;
        if (fa !== fb) return fa - fb;
        if (isMonsterCard(a) && isMonsterCard(b)) {
            const la = a.level || 0;
            const lb = b.level || 0;
            if (la !== lb) return lb - la;
            const aa = a.atk !== null && a.atk !== undefined ? a.atk : -2;
            const ab = b.atk !== null && b.atk !== undefined ? b.atk : -2;
            if (aa !== ab) return ab - aa;
        }
        return (a.name || '').localeCompare(b.name || '');
    };
    state.playerDeck.main.sort(cmp);
    state.playerDeck.extra.sort(cmp);
    state.playerDeck.side.sort(cmp);
    pushHistory(true);
    renderDeck();
    showToast('Deck sorted by card type, level, and ATK.', 'info');
}

/* ==================== RENDER DECK & COUNTERS ==================== */
function renderDeck() {
    const mainLen = state.playerDeck.main.length;
    const extraLen = state.playerDeck.extra.length;
    const sideLen = state.playerDeck.side.length;

    document.getElementById('count-main').textContent = mainLen;
    document.getElementById('count-extra').textContent = extraLen;
    document.getElementById('count-side').textContent = sideLen;

    document.getElementById('summary-main').textContent = mainLen;
    document.getElementById('summary-extra').textContent = extraLen;
    document.getElementById('summary-side').textContent = sideLen;

    const validityBadge = document.getElementById('main-validity-badge');
    if (mainLen >= 40 && mainLen <= 60) {
        validityBadge.textContent = 'Tournament legal (40-60)';
        validityBadge.className = 'validity-badge valid';
    } else if (mainLen < 40) {
        validityBadge.textContent = `${40 - mainLen} more to reach 40`;
        validityBadge.className = 'validity-badge warn';
    } else {
        validityBadge.textContent = `${mainLen - 60} over standard 60`;
        validityBadge.className = 'validity-badge over';
    }

    // 6-type breakdown (Tag Force 2 style)
    const counts = { normal: 0, effect: 0, fusion: 0, ritual: 0, spell: 0, trap: 0 };
    for (const c of state.playerDeck.main) {
        const f = getCardFrame(c);
        if (counts[f] !== undefined) counts[f]++;
    }
    for (const c of state.playerDeck.extra) {
        counts.fusion++;
    }
    document.getElementById('cnt-normal').textContent = counts.normal;
    document.getElementById('cnt-effect').textContent = counts.effect;
    document.getElementById('cnt-fusion').textContent = counts.fusion;
    document.getElementById('cnt-ritual').textContent = counts.ritual;
    document.getElementById('cnt-spell').textContent = counts.spell;
    document.getElementById('cnt-trap').textContent = counts.trap;

    renderDeckGrid('main-deck-grid', state.playerDeck.main, 'main', 'Main Deck is empty. Add cards from the database on the right.');
    renderDeckGrid('extra-deck-grid', state.playerDeck.extra, 'extra', 'No Fusion Monsters in Extra Deck.');
    renderDeckGrid('side-deck-grid', state.playerDeck.side, 'side', 'Side Deck is empty (up to 15 cards).');
}

function renderDeckGrid(gridId, cards, targetDeck, emptyMsg) {
    const grid = document.getElementById(gridId);
    const frag = document.createDocumentFragment();
    if (cards.length === 0) {
        const empty = document.createElement('div');
        empty.className = 'grid-empty-state';
        empty.textContent = emptyMsg;
        frag.appendChild(empty);
    } else {
        cards.forEach((card, idx) => {
            frag.appendChild(buildDeckTileElement(card, idx, targetDeck, true));
        });
    }
    grid.replaceChildren(frag);
}

/* ==================== SEARCH, FILTER, SORT & PAGINATION ==================== */
function scheduleSearch() {
    clearTimeout(state.searchTimer);
    const inputVal = document.getElementById('search-input').value;
    document.getElementById('btn-search-clear').hidden = inputVal.length === 0;
    document.getElementById('search-kbd-hint').hidden = inputVal.length > 0;
    state.searchTimer = setTimeout(handleSearch, 120);
}

function handleSearch() {
    const query = document.getElementById('search-input').value.toLowerCase().trim();
    const frameFilter = document.getElementById('filter-frame').value;
    const attrFilter = document.getElementById('filter-attribute').value;
    const sortBy = document.getElementById('sort-results').value;

    const results = state.cardsDb.filter(card => {
        if (!card || !card.name) return false;

        if (frameFilter !== 'all') {
            if (frameFilter === 'anime') {
                if (!card.is_anime) return false;
            } else if (getCardFrame(card) !== frameFilter) {
                return false;
            }
        }

        if (attrFilter !== 'all') {
            if (card.attribute !== attrFilter) return false;
        }

        if (query) {
            const nameMatch = card.name.toLowerCase().includes(query);
            const passcodeMatch = typeof card.passcode === 'string' && card.passcode.includes(query);
            const typeMatch = (card.type || '').toLowerCase().includes(query);
            const raceMatch = (card.race || '').toLowerCase().includes(query);
            const attrMatch = (card.attribute || '').toLowerCase().includes(query);
            const descText = getCardDescription(card);
            const descMatch = descText ? descText.toLowerCase().includes(query) : false;
            if (!(nameMatch || passcodeMatch || typeMatch || raceMatch || attrMatch || descMatch)) {
                return false;
            }
        }
        return true;
    });

    if (sortBy === 'atk') {
        results.sort((a, b) => {
            const va = isMonsterCard(a) && a.atk !== null && a.atk !== undefined ? a.atk : -9999;
            const vb = isMonsterCard(b) && b.atk !== null && b.atk !== undefined ? b.atk : -9999;
            return vb - va || a.name.localeCompare(b.name);
        });
    } else if (sortBy === 'def') {
        results.sort((a, b) => {
            const va = isMonsterCard(a) && a.def !== null && a.def !== undefined ? a.def : -9999;
            const vb = isMonsterCard(b) && b.def !== null && b.def !== undefined ? b.def : -9999;
            return vb - va || a.name.localeCompare(b.name);
        });
    } else if (sortBy === 'level') {
        results.sort((a, b) => ((b.level || 0) - (a.level || 0)) || a.name.localeCompare(b.name));
    } else {
        results.sort((a, b) => a.name.localeCompare(b.name));
    }

    state.filteredCards = results;
    state.currentPage = 1;
    renderDatabaseResults(true);
}

function renderDatabaseResults(scrollTop = false) {
    const listEl = document.getElementById('database-grid');
    const pag = document.getElementById('pagination');
    const matchCount = document.getElementById('search-match-count');

    const total = state.filteredCards.length;
    if (total === 0) {
        matchCount.textContent = '0 matches';
        const empty = document.createElement('div');
        empty.className = 'grid-empty-state';
        empty.textContent = 'No cards match your current filters.';
        listEl.replaceChildren(empty);
        pag.hidden = true;
        return;
    }

    const totalPages = Math.ceil(total / CARDS_PER_PAGE);
    if (state.currentPage > totalPages) state.currentPage = totalPages;

    const startIdx = (state.currentPage - 1) * CARDS_PER_PAGE;
    const endIdx = Math.min(startIdx + CARDS_PER_PAGE, total);
    matchCount.textContent = `${startIdx + 1}-${endIdx} of ${total.toLocaleString()}`;

    pag.hidden = totalPages <= 1;
    document.getElementById('page-num').textContent = `Page ${state.currentPage} / ${totalPages}`;
    document.getElementById('btn-page-prev').disabled = state.currentPage <= 1;
    document.getElementById('btn-page-next').disabled = state.currentPage >= totalPages;

    const copyMap = getDeckCopyMap();
    const frag = document.createDocumentFragment();
    const pageCards = state.filteredCards.slice(startIdx, endIdx);

    for (const card of pageCards) {
        frag.appendChild(buildSearchResultRow(card, copyMap.get(card.name) || 0));
    }
    listEl.replaceChildren(frag);

    if (scrollTop) {
        document.getElementById('search-results-container').scrollTop = 0;
    }
}

function buildSearchResultRow(card, inDeckCount) {
    const frame = getCardFrame(card);
    const isFusion = isFusionCard(card);
    const maxed = inDeckCount >= 3;

    const row = document.createElement('div');
    row.className = 'search-result-item';
    row.setAttribute('role', 'listitem');
    row.tabIndex = 0;

    row.appendChild(buildSearchThumbnail(card));

    const details = document.createElement('div');
    details.className = 'result-details';

    const nameRow = document.createElement('div');
    nameRow.className = 'result-name-row';

    const nameEl = document.createElement('span');
    nameEl.className = 'result-name';
    nameEl.textContent = card.name;
    nameRow.appendChild(nameEl);

    if (inDeckCount > 0) {
        const pill = document.createElement('span');
        pill.className = `in-deck-pill${maxed ? ' maxed' : ''}`;
        pill.textContent = `${inDeckCount}/3`;
        nameRow.appendChild(pill);
    }
    details.appendChild(nameRow);

    const meta = document.createElement('div');
    meta.className = 'result-meta';

    const frameSpan = document.createElement('span');
    frameSpan.className = `meta-frame-${frame}`;
    frameSpan.textContent = frame === 'anime' ? 'Anime' : frame.charAt(0).toUpperCase() + frame.slice(1);
    meta.appendChild(frameSpan);

    const metaParts = [];
    if (card.race && card.race !== 'Unknown') metaParts.push(card.race);
    if (card.attribute) metaParts.push(card.attribute);
    if (card.level) metaParts.push(`\u2605${card.level}`);
    if (isMonsterCard(card)) metaParts.push(`${formatStat(card.atk)}/${formatStat(card.def)}`);

    if (metaParts.length > 0) {
        const rest = document.createElement('span');
        rest.textContent = `\u00b7 ${metaParts.join(' \u00b7 ')}`;
        meta.appendChild(rest);
    }
    details.appendChild(meta);
    row.appendChild(details);

    // High-contrast always-visible actions
    const actions = document.createElement('div');
    actions.className = 'result-actions';

    const addPrimary = document.createElement('button');
    addPrimary.type = 'button';
    addPrimary.className = `action-add-btn ${isFusion ? 'add-extra' : 'add-main'}`;
    addPrimary.textContent = isFusion ? '+E' : '+M';
    addPrimary.title = isFusion ? 'Add to Extra Deck' : 'Add to Main Deck';
    addPrimary.disabled = maxed;
    addPrimary.addEventListener('click', (e) => {
        e.stopPropagation();
        addCard(card, isFusion ? 'extra' : 'main');
    });
    actions.appendChild(addPrimary);

    const addSide = document.createElement('button');
    addSide.type = 'button';
    addSide.className = 'action-add-btn add-side';
    addSide.textContent = '+S';
    addSide.title = 'Add to Side Deck';
    addSide.disabled = maxed;
    addSide.addEventListener('click', (e) => {
        e.stopPropagation();
        addCard(card, 'side');
    });
    actions.appendChild(addSide);

    row.appendChild(actions);

    row.addEventListener('mouseenter', () => previewCard(card));
    row.addEventListener('focus', () => previewCard(card));
    row.addEventListener('click', () => pinCard(card));
    row.addEventListener('dblclick', () => addCard(card, isFusion ? 'extra' : 'main'));
    row.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
            e.preventDefault();
            addCard(card, isFusion ? 'extra' : 'main');
        }
    });

    return row;
}

function changePage(delta) {
    const totalPages = Math.ceil(state.filteredCards.length / CARDS_PER_PAGE);
    const next = state.currentPage + delta;
    if (next >= 1 && next <= totalPages) {
        state.currentPage = next;
        renderDatabaseResults(true);
    }
}

/* ==================== ANALYTICS & OPENING HAND SIMULATOR ==================== */
function openAnalyticsModal(autoDraw = true) {
    renderAnalytics();
    if (autoDraw || state.currentHand.length === 0) {
        drawNewHand();
    }
    openModal('modal-analytics');
}

function renderAnalytics() {
    const main = state.playerDeck.main;
    const extra = state.playerDeck.extra;
    const totalMain = Math.max(main.length, 1);

    const catCounts = {
        normal: { label: 'Normal', count: 0, color: FRAME_COLORS.normal },
        effect: { label: 'Effect', count: 0, color: FRAME_COLORS.effect },
        ritual: { label: 'Ritual', count: 0, color: FRAME_COLORS.ritual },
        fusion: { label: 'Fusion (Ex)', count: extra.length, color: FRAME_COLORS.fusion },
        spell: { label: 'Spell', count: 0, color: FRAME_COLORS.spell },
        trap: { label: 'Trap', count: 0, color: FRAME_COLORS.trap },
        anime: { label: 'Anime', count: 0, color: FRAME_COLORS.anime }
    };

    const levels = { low: 0, mid: 0, high: 0 };
    let monsterCount = 0;
    let atkSum = 0;
    let atkCount = 0;
    let defSum = 0;
    let defCount = 0;
    const attrCounts = new Map();
    const raceCounts = new Map();

    for (const c of main) {
        const f = getCardFrame(c);
        if (catCounts[f]) catCounts[f].count++;
        if (isMonsterCard(c)) {
            monsterCount++;
            const lv = c.level || 0;
            if (lv <= 4) levels.low++;
            else if (lv <= 6) levels.mid++;
            else levels.high++;
            if (typeof c.atk === 'number' && c.atk >= 0) { atkSum += c.atk; atkCount++; }
            if (typeof c.def === 'number' && c.def >= 0) { defSum += c.def; defCount++; }
        }
        if (c.attribute) attrCounts.set(c.attribute, (attrCounts.get(c.attribute) || 0) + 1);
        if (c.race && c.race !== 'Unknown') raceCounts.set(c.race, (raceCounts.get(c.race) || 0) + 1);
    }

    const catHost = document.getElementById('analytics-categories');
    catHost.innerHTML = '';
    const maxCat = Math.max(totalMain, extra.length, 1);
    Object.values(catCounts).forEach(item => {
        if (item.label === 'Anime' && item.count === 0) return;
        catHost.appendChild(buildBarRow(item.label, item.count, maxCat, item.color));
    });

    const lvlHost = document.getElementById('analytics-levels');
    lvlHost.innerHTML = '';
    const maxLvl = Math.max(monsterCount, 1);
    lvlHost.appendChild(buildBarRow('Lv 1 - 4', levels.low, maxLvl, '#34d399'));
    lvlHost.appendChild(buildBarRow('Lv 5 - 6', levels.mid, maxLvl, '#f59e0b'));
    lvlHost.appendChild(buildBarRow('Lv 7+', levels.high, maxLvl, '#a855f7'));

    const avgEl = document.getElementById('analytics-avg-stats');
    const avgAtk = atkCount ? Math.round(atkSum / atkCount) : 0;
    const avgDef = defCount ? Math.round(defSum / defCount) : 0;
    avgEl.innerHTML = `<span>Monsters: <strong>${monsterCount}</strong></span><span>Avg ATK: <strong>${avgAtk}</strong></span><span>Avg DEF: <strong>${avgDef}</strong></span>`;

    const chipHost = document.getElementById('analytics-attributes');
    chipHost.innerHTML = '';
    const sortedAttrs = Array.from(attrCounts.entries()).sort((a, b) => b[1] - a[1]);
    const sortedRaces = Array.from(raceCounts.entries()).sort((a, b) => b[1] - a[1]).slice(0, 8);
    if (sortedAttrs.length === 0 && sortedRaces.length === 0) {
        chipHost.innerHTML = '<span class="muted-note">Add cards to your Main Deck to view distribution.</span>';
    } else {
        sortedAttrs.forEach(([attr, cnt]) => {
            const chip = document.createElement('span');
            chip.className = 'stat-chip';
            chip.style.borderColor = ATTR_COLORS[attr] || 'rgba(255,255,255,0.12)';
            chip.textContent = `${attr}: ${cnt}`;
            chipHost.appendChild(chip);
        });
        sortedRaces.forEach(([race, cnt]) => {
            const chip = document.createElement('span');
            chip.className = 'stat-chip';
            chip.textContent = `${race}: ${cnt}`;
            chipHost.appendChild(chip);
        });
    }
}

function buildBarRow(label, count, maxVal, color) {
    const row = document.createElement('div');
    row.className = 'bar-row';

    const lbl = document.createElement('span');
    lbl.textContent = label;
    row.appendChild(lbl);

    const track = document.createElement('div');
    track.className = 'bar-track';
    const fill = document.createElement('div');
    fill.className = 'bar-fill';
    fill.style.width = `${Math.round((count / Math.max(maxVal, 1)) * 100)}%`;
    fill.style.backgroundColor = color;
    track.appendChild(fill);
    row.appendChild(track);

    const val = document.createElement('span');
    val.className = 'bar-val';
    val.textContent = String(count);
    row.appendChild(val);

    return row;
}

function drawNewHand() {
    const pool = [...state.playerDeck.main];
    for (let i = pool.length - 1; i > 0; i--) {
        const j = Math.floor(Math.random() * (i + 1));
        [pool[i], pool[j]] = [pool[j], pool[i]];
    }
    state.currentHand = pool.splice(0, 5);
    state.handDeckPool = pool;
    renderHandSimulator();
}

function drawExtraCard() {
    if (state.handDeckPool.length === 0) {
        showToast('No cards remaining in simulated deck.', 'info');
        return;
    }
    state.currentHand.push(state.handDeckPool.shift());
    renderHandSimulator();
}

function renderHandSimulator() {
    const host = document.getElementById('hand-sim-cards');
    const summary = document.getElementById('hand-sim-summary');
    const drawExtraBtn = document.getElementById('btn-draw-extra');

    drawExtraBtn.disabled = state.handDeckPool.length === 0;

    if (state.currentHand.length === 0) {
        host.innerHTML = '<div class="grid-empty-state">Add cards to your Main Deck to simulate opening hands.</div>';
        summary.textContent = 'Main Deck is empty.';
        return;
    }

    let m = 0, s = 0, t = 0;
    const frag = document.createDocumentFragment();
    state.currentHand.forEach((card, i) => {
        const f = getCardFrame(card);
        if (isMonsterCard(card)) m++;
        else if (f === 'spell') s++;
        else if (f === 'trap') t++;
        frag.appendChild(buildDeckTileElement(card, i, 'hand', false));
    });
    host.replaceChildren(frag);
    summary.textContent = `Hand (${state.currentHand.length}): ${m} Monster${m !== 1 ? 's' : ''} \u00b7 ${s} Spell${s !== 1 ? 's' : ''} \u00b7 ${t} Trap${t !== 1 ? 's' : ''} \u00b7 ${state.handDeckPool.length} left in deck`;
}

/* ==================== IMPORT / EXPORT (.YDK & .JSON) ==================== */
function exportYdk() {
    const lines = ['#created by Duelist Hub (Tag Force 2 Deck Editor)', '#main'];
    const skippedAnime = [];

    const pushSection = (cards) => {
        for (const c of cards) {
            if (isValidArtPasscode(c.passcode) && !c.is_anime) {
                lines.push(String(parseInt(c.passcode, 10)));
            } else {
                skippedAnime.push(c.name);
                lines.push(`# anime/no-passcode skipped: ${c.name}`);
            }
        }
    };

    pushSection(state.playerDeck.main);
    lines.push('#extra');
    pushSection(state.playerDeck.extra);
    lines.push('!side');
    pushSection(state.playerDeck.side);

    const safeName = (state.playerDeck.name || 'deck').replace(/[^a-z0-9_-]+/gi, '_');
    downloadTextFile(`${safeName}.ydk`, lines.join('\n') + '\n', 'text/plain');
    if (skippedAnime.length > 0) {
        showToast(`Exported .ydk (${skippedAnime.length} anime card(s) noted as comments).`, 'warning');
    } else {
        showToast(`Exported ${safeName}.ydk`, 'success');
    }
}

function exportJson() {
    const payload = {
        name: state.playerDeck.name,
        main: state.playerDeck.main.map(c => c.game_index),
        extra: state.playerDeck.extra.map(c => c.game_index),
        side: state.playerDeck.side.map(c => c.game_index)
    };
    const safeName = (state.playerDeck.name || 'deck').replace(/[^a-z0-9_-]+/gi, '_');
    downloadTextFile(`${safeName}.json`, JSON.stringify(payload, null, 2), 'application/json');
    showToast(`Exported ${safeName}.json`, 'success');
}

function copyDecklistText() {
    const formatSection = (title, cards) => {
        const grouped = new Map();
        for (const c of cards) grouped.set(c.name, (grouped.get(c.name) || 0) + 1);
        const rows = Array.from(grouped.entries()).map(([n, cnt]) => `${cnt}x ${n}`);
        return `${title} (${cards.length}):\n${rows.length ? rows.join('\n') : '(empty)'}`;
    };
    const text = [
        `Deck: ${state.playerDeck.name}`,
        '',
        formatSection('Main Deck', state.playerDeck.main),
        '',
        formatSection('Extra Deck', state.playerDeck.extra),
        '',
        formatSection('Side Deck', state.playerDeck.side)
    ].join('\n');

    if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text)
            .then(() => showToast('Decklist copied to clipboard.', 'success'))
            .catch(() => showToast('Clipboard write blocked by browser.', 'warning'));
    } else {
        showToast('Clipboard API unavailable in this context.', 'warning');
    }
}

function downloadTextFile(filename, content, mime) {
    const blob = new Blob([content], { type: mime });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function importDeckContent(rawText, filename = '') {
    const trimmed = rawText.trim();
    if (!trimmed) {
        showToast('Nothing to import.', 'warning');
        return;
    }

    let nextName = state.playerDeck.name;
    const nextMain = [];
    const nextExtra = [];
    const nextSide = [];
    let unknownCount = 0;
    let skippedLimit = 0;
    const copyCounter = new Map();

    const tryPush = (card, target) => {
        if (!card) { unknownCount++; return; }
        let dest = target;
        if (dest === 'main' && isFusionCard(card)) dest = 'extra';
        if (dest === 'extra' && !isFusionCard(card)) dest = 'main';
        const cur = copyCounter.get(card.name) || 0;
        if (cur >= 3) { skippedLimit++; return; }
        if (dest === 'main' && nextMain.length >= MAX_MAIN) { skippedLimit++; return; }
        if (dest === 'extra' && nextExtra.length >= MAX_EXTRA) { skippedLimit++; return; }
        if (dest === 'side' && nextSide.length >= MAX_SIDE) { skippedLimit++; return; }
        copyCounter.set(card.name, cur + 1);
        if (dest === 'main') nextMain.push(card);
        else if (dest === 'extra') nextExtra.push(card);
        else nextSide.push(card);
    };

    if (trimmed.startsWith('{')) {
        try {
            const parsed = JSON.parse(trimmed);
            if (typeof parsed.name === 'string' && parsed.name.trim()) nextName = parsed.name.trim();
            (parsed.main || []).forEach(e => tryPush(resolveCardEntry(e), 'main'));
            (parsed.extra || []).forEach(e => tryPush(resolveCardEntry(e), 'extra'));
            (parsed.side || []).forEach(e => tryPush(resolveCardEntry(e), 'side'));
        } catch (err) {
            showToast('Invalid JSON deck format.', 'error');
            return;
        }
    } else {
        // Parse .ydk
        if (filename) {
            const base = filename.replace(/\.(ydk|txt)$/i, '').replace(/[_-]+/g, ' ').trim();
            if (base) nextName = base.slice(0, 30);
        }
        let section = 'main';
        for (const rawLine of trimmed.split(/\r?\n/)) {
            const line = rawLine.trim();
            if (!line) continue;
            if (line === '#main') { section = 'main'; continue; }
            if (line === '#extra') { section = 'extra'; continue; }
            if (line === '!side') { section = 'side'; continue; }
            if (line.startsWith('#')) continue;
            const digits = line.replace(/\D/g, '');
            if (!digits) continue;
            const card = state.cardsByPasscode.get(digits) || state.cardsByPasscode.get(digits.padStart(8, '0'));
            tryPush(card, section);
        }
    }

    if (nextMain.length === 0 && nextExtra.length === 0 && nextSide.length === 0) {
        showToast('No matching Tag Force 2 cards found in import.', 'warning');
        return;
    }

    state.playerDeck.name = nextName;
    state.playerDeck.main = nextMain;
    state.playerDeck.extra = nextExtra;
    state.playerDeck.side = nextSide;
    document.getElementById('deck-name-input').value = nextName;
    pushHistory(true);
    renderDeck();
    renderDatabaseResults();
    if (nextMain.length > 0) pinCard(nextMain[0]);
    closeModal('modal-io');

    const notes = [];
    if (unknownCount > 0) notes.push(`${unknownCount} not in TF2 DB`);
    if (skippedLimit > 0) notes.push(`${skippedLimit} over limit`);
    showToast(
        `Imported ${nextMain.length + nextExtra.length + nextSide.length} cards` + (notes.length ? ` (${notes.join(', ')})` : '.'),
        unknownCount > 0 ? 'warning' : 'success'
    );
}

/* ==================== BACKEND API & PERSISTENCE ==================== */
function saveDeck(skipSizeCheck = false) {
    const deckName = document.getElementById('deck-name-input').value.trim();
    if (!deckName) {
        showToast('Please enter a deck name before saving.', 'warning');
        document.getElementById('deck-name-input').focus();
        return;
    }

    state.playerDeck.name = deckName;

    if (!skipSizeCheck && (state.playerDeck.main.length < 40 || state.playerDeck.main.length > 60)) {
        openConfirmModal(
            'Non-Standard Main Deck Size',
            `Standard Yu-Gi-Oh! Main Decks contain 40 to 60 cards, and you currently have ${state.playerDeck.main.length}. Save anyway?`,
            'Save Anyway',
            () => saveDeck(true)
        );
        return;
    }

    const payload = {
        name: state.playerDeck.name,
        main: state.playerDeck.main.map(c => c.game_index),
        side: state.playerDeck.side.map(c => c.game_index),
        extra: state.playerDeck.extra.map(c => c.game_index),
        auto_unlock: state.autoUnlock
    };

    if (!state.backendAvailable) {
        try {
            localStorage.setItem(STATIC_STORAGE_KEY, JSON.stringify(payload));
            setDirty(false);
            showToast('Deck saved to browser localStorage (Static Demo Mode).', 'success');
        } catch (err) {
            showToast('Could not write to browser storage.', 'error');
        }
        return;
    }

    const saveBtn = document.getElementById('btn-save');
    const saveLabel = document.getElementById('btn-save-label');
    saveBtn.disabled = true;
    saveLabel.textContent = 'Saving...';

    fetch('/api/save_deck', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
    })
        .then(async res => {
            const data = await res.json().catch(() => ({}));
            if (!res.ok || data.status === 'error') {
                throw new Error(data.message || `HTTP ${res.status}`);
            }
            return data;
        })
        .then(data => {
            setDirty(false);
            showToast(data.message || 'Deck saved successfully.', 'success');
            return refreshServerStatus();
        })
        .catch(err => {
            showToast(`Save failed: ${err.message}`, 'error');
        })
        .finally(() => {
            saveBtn.disabled = false;
            saveLabel.textContent = 'Save';
        });
}

async function refreshServerStatus() {
    if (!state.backendAvailable) return;
    try {
        const res = await fetch('/api/status', { cache: 'no-store' });
        if (!res.ok) return;
        const statusData = await res.json();
        applyServerStatus(statusData);
    } catch (_) {
        // Ignore transient status refresh error
    }
}

function applyServerStatus(info) {
    state.serverStatus = { ...state.serverStatus, ...info };
    if (typeof info.auto_unlock_default === 'boolean' && state.deckHistory.length === 0) {
        state.autoUnlock = info.auto_unlock_default;
    }

    const pill = document.getElementById('status-pill');
    const pillText = document.getElementById('status-pill-text');
    const encBanner = document.getElementById('encrypted-banner');

    pill.classList.remove('status-loading', 'status-demo', 'status-save', 'status-encrypted');

    if (!state.backendAvailable) {
        pill.classList.add('status-demo');
        pillText.textContent = 'DEMO MODE (STATIC)';
        pill.title = 'Running statically in browser — edits save to localStorage';
        encBanner.hidden = true;
    } else if (info.encrypted) {
        pill.classList.add('status-encrypted');
        pillText.textContent = 'ENCRYPTED SAVE';
        pill.title = 'Detected encrypted DATA0 — click for Save Manager';
        encBanner.hidden = false;
    } else if (info.mode === 'save') {
        pill.classList.add('status-save');
        const regionTag = info.region ? ` \u00b7 ${info.region}` : '';
        pillText.textContent = `PSP SAVE CONNECTED${regionTag}`;
        pill.title = info.save_path || 'Connected to local DATA0 save file';
        encBanner.hidden = true;
    } else {
        pill.classList.add('status-demo');
        pillText.textContent = 'DEMO MODE';
        pill.title = 'No PSP save found — editing Demo Deck (upload DATA0 in Save File)';
        encBanner.hidden = true;
    }

    // Update Settings modal controls
    const artToggle = document.getElementById('toggle-art-cache');
    artToggle.checked = Boolean(state.serverStatus.art_cache_enabled);
    artToggle.disabled = !state.backendAvailable;

    const artDirNote = document.getElementById('art-dir-note');
    if (state.serverStatus.art_dir_configured) {
        artDirNote.hidden = false;
        artDirNote.textContent = 'TAGFORCE_ART_DIR is configured — local artwork directory is active.';
    } else {
        artDirNote.hidden = true;
    }

    const syncBtn = document.getElementById('btn-sync-descriptions');
    syncBtn.disabled = !state.backendAvailable;
    const textCount = Object.keys(state.cardDescriptions).length || state.serverStatus.text_cache_count || 0;
    document.getElementById('text-cache-status').textContent = state.backendAvailable
        ? `Cached locally: ${textCount.toLocaleString()} card descriptions`
        : 'Requires local Python server (run_showcase.py)';

    document.getElementById('toggle-auto-unlock').checked = state.autoUnlock;

    renderSaveManagerModal();
}

function renderSaveManagerModal() {
    const infoBox = document.getElementById('save-info-box');
    const downloadBtn = document.getElementById('btn-download-save');
    const uploadInput = document.getElementById('upload-save-input');
    const backupList = document.getElementById('backup-list');

    if (!state.backendAvailable) {
        infoBox.innerHTML = '<div><strong>Mode:</strong> Static Browser Demo (no Python backend)</div><div class="muted-note">Run <code>python run_showcase.py</code> locally to edit, upload, download, and backup real PPSSPP <code>DATA0</code> save files.</div>';
        downloadBtn.disabled = true;
        uploadInput.disabled = true;
        backupList.innerHTML = '<div class="muted-note">Unavailable in static browser mode.</div>';
        return;
    }

    uploadInput.disabled = false;
    const isSaveMode = state.serverStatus.mode === 'save';
    downloadBtn.disabled = !isSaveMode;

    const offsetHex = typeof state.serverStatus.deck_offset === 'number'
        ? `0x${state.serverStatus.deck_offset.toString(16).toUpperCase()}`
        : 'N/A';

    infoBox.innerHTML = '';
    const lines = [
        ['Mode', isSaveMode ? 'PSP Save Active' : 'Demo Mode (In-Memory)'],
        ['Region', state.serverStatus.region || 'Not connected'],
        ['Deck Offset', offsetHex],
        ['Save Path', state.serverStatus.save_path || 'None (upload DATA0 below)']
    ];
    for (const [k, v] of lines) {
        const div = document.createElement('div');
        const strong = document.createElement('strong');
        strong.textContent = `${k}: `;
        div.appendChild(strong);
        div.appendChild(document.createTextNode(String(v)));
        infoBox.appendChild(div);
    }

    const backups = Array.isArray(state.serverStatus.backups) ? state.serverStatus.backups : [];
    backupList.innerHTML = '';
    if (backups.length === 0) {
        backupList.innerHTML = '<div class="muted-note">No backups found yet. Save your deck to create an automatic backup.</div>';
        return;
    }

    backups.forEach(entry => {
        const name = typeof entry === 'string' ? entry : (entry.name || String(entry));
        const row = document.createElement('div');
        row.className = 'backup-item';

        const span = document.createElement('span');
        span.textContent = name;
        row.appendChild(span);

        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'btn btn-xs';
        btn.textContent = 'Restore';
        btn.addEventListener('click', () => restoreBackupFile(name));
        row.appendChild(btn);

        backupList.appendChild(row);
    });
}

async function handleSaveUpload(file) {
    if (!file || !state.backendAvailable) return;
    try {
        const buf = await file.arrayBuffer();
        const res = await fetch('/api/upload_save', {
            method: 'POST',
            headers: { 'Content-Type': 'application/octet-stream' },
            body: buf
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok || data.status === 'error') {
            throw new Error(data.message || `Upload failed (${res.status})`);
        }
        if (data.status_info) applyServerStatus(data.status_info);
        if (data.deck) loadDeckData(data.deck, true);
        showToast('DATA0 uploaded and loaded successfully!', 'success');
        closeModal('modal-save-mgr');
    } catch (err) {
        showToast(`Upload error: ${err.message}`, 'error');
    }
}

async function restoreBackupFile(backupName) {
    if (!state.backendAvailable) return;
    try {
        const res = await fetch('/api/restore_backup', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ backup: backupName })
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok || data.status === 'error') {
            throw new Error(data.message || `Restore failed (${res.status})`);
        }
        if (Array.isArray(data.backups)) {
            state.serverStatus.backups = data.backups;
        }
        if (data.deck) loadDeckData(data.deck, true);
        renderSaveManagerModal();
        showToast(`Restored backup: ${backupName}`, 'success');
    } catch (err) {
        showToast(`Restore error: ${err.message}`, 'error');
    }
}

async function toggleArtCacheSetting(enabled) {
    if (!state.backendAvailable) return;
    try {
        const res = await fetch('/api/settings', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ art_cache_enabled: enabled })
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(data.message || `HTTP ${res.status}`);
        state.serverStatus.art_cache_enabled = Boolean(data.art_cache_enabled ?? enabled);
        state.failedArtCache.clear();
        renderDeck();
        renderDatabaseResults();
        const active = getActiveInspectedCard();
        if (active) renderInspector(active);
        showToast(
            state.serverStatus.art_cache_enabled
                ? 'Local YGOPRODeck art cache enabled.'
                : 'Switched back to art-free procedural card frames.',
            'info'
        );
    } catch (err) {
        document.getElementById('toggle-art-cache').checked = state.serverStatus.art_cache_enabled;
        showToast(`Settings error: ${err.message}`, 'error');
    }
}

async function syncDescriptionsLocally() {
    if (!state.backendAvailable) return;
    const btn = document.getElementById('btn-sync-descriptions');
    btn.disabled = true;
    btn.textContent = 'Syncing...';
    try {
        const res = await fetch('/api/sync_descriptions', { method: 'POST' });
        const data = await res.json().catch(() => ({}));
        if (!res.ok || data.status === 'error') {
            throw new Error(data.message || `HTTP ${res.status}`);
        }
        await loadCardDescriptions();
        const count = Object.keys(state.cardDescriptions).length;
        state.serverStatus.text_cache_count = count;
        document.getElementById('text-cache-status').textContent = `Cached locally: ${count.toLocaleString()} card descriptions`;
        const active = getActiveInspectedCard();
        if (active) renderInspector(active);
        showToast(`Synced ${count.toLocaleString()} card descriptions locally.`, 'success');
    } catch (err) {
        showToast(`Description sync failed: ${err.message}`, 'error');
    } finally {
        btn.disabled = false;
        btn.textContent = 'Sync Card Effect Text Locally';
    }
}

async function loadCardDescriptions() {
    try {
        const res = await fetch('/api/card_descriptions', { cache: 'no-store' });
        if (res.ok) {
            const map = await res.json();
            if (map && typeof map === 'object') {
                state.cardDescriptions = map;
            }
        }
    } catch (_) {
        // Optional endpoint; ignore in static mode
    }
}

/* ==================== LOAD DECK HELPER ==================== */
function loadDeckData(data, resetHistory = true) {
    state.playerDeck.name = (data && data.name) ? String(data.name) : 'Starting Deck';
    state.playerDeck.main = (data && Array.isArray(data.main) ? data.main : []).map(resolveCardEntry).filter(Boolean);
    state.playerDeck.extra = (data && Array.isArray(data.extra) ? data.extra : []).map(resolveCardEntry).filter(Boolean);
    state.playerDeck.side = (data && Array.isArray(data.side) ? data.side : []).map(resolveCardEntry).filter(Boolean);

    document.getElementById('deck-name-input').value = state.playerDeck.name;

    if (resetHistory) {
        state.deckHistory = [];
        state.historyIndex = -1;
        pushHistory(false);
        setDirty(false);
    }

    renderDeck();
    renderDatabaseResults();

    if (state.playerDeck.main.length > 0) {
        previewCard(state.playerDeck.main[0]);
    } else if (state.cardsDb.length > 0) {
        previewCard(state.cardsDb[0]);
    }
}

/* ==================== INITIALIZATION & EVENT BINDING ==================== */
function bindEvents() {
    // Header & Modal Openers
    document.getElementById('status-pill').addEventListener('click', () => {
        renderSaveManagerModal();
        openModal('modal-save-mgr');
    });
    document.getElementById('btn-open-analytics').addEventListener('click', () => openAnalyticsModal(true));
    document.getElementById('btn-quick-hand').addEventListener('click', () => openAnalyticsModal(true));
    document.getElementById('btn-open-io').addEventListener('click', () => openModal('modal-io'));
    document.getElementById('btn-open-save-mgr').addEventListener('click', () => {
        renderSaveManagerModal();
        openModal('modal-save-mgr');
    });
    document.getElementById('btn-open-settings').addEventListener('click', () => openModal('modal-settings'));
    document.getElementById('btn-desc-sync-hint').addEventListener('click', () => openModal('modal-settings'));
    document.getElementById('btn-dismiss-encrypted').addEventListener('click', () => {
        document.getElementById('encrypted-banner').hidden = true;
    });

    // Modal close buttons & backdrop clicks
    document.querySelectorAll('[data-close-modal]').forEach(btn => {
        btn.addEventListener('click', () => closeModal(btn.dataset.closeModal));
    });
    document.querySelectorAll('.modal-backdrop').forEach(backdrop => {
        backdrop.addEventListener('click', (e) => {
            if (e.target === backdrop) closeModal(backdrop.id);
        });
    });

    // Confirmation modal
    document.getElementById('btn-confirm-cancel').addEventListener('click', () => closeModal('modal-confirm'));
    document.getElementById('btn-confirm-ok').addEventListener('click', () => {
        const cb = state.confirmCallback;
        closeModal('modal-confirm');
        if (typeof cb === 'function') cb();
    });

    // Inspector controls
    document.getElementById('pin-badge').addEventListener('click', () => {
        if (state.pinnedCard) {
            unpinCard();
        } else if (state.hoveredCard) {
            pinCard(state.hoveredCard);
        }
    });
    document.getElementById('btn-inspector-add-main').addEventListener('click', () => {
        const card = getActiveInspectedCard();
        if (card) addCard(card, isFusionCard(card) ? 'extra' : 'main');
    });
    document.getElementById('btn-inspector-add-side').addEventListener('click', () => {
        const card = getActiveInspectedCard();
        if (card) addCard(card, 'side');
    });

    // Deck name input (live sync + debounced Undo history snapshot)
    const nameInput = document.getElementById('deck-name-input');
    nameInput.addEventListener('input', () => {
        state.playerDeck.name = nameInput.value;
        setDirty(true);
        clearTimeout(state.nameHistoryTimer);
        state.nameHistoryTimer = setTimeout(() => {
            const latest = state.deckHistory[state.historyIndex];
            if (!latest || latest.name !== state.playerDeck.name) {
                pushHistory(true);
            }
        }, 450);
    });

    // Deck toolbar buttons
    document.getElementById('btn-save').addEventListener('click', () => saveDeck(false));
    document.getElementById('btn-undo').addEventListener('click', undo);
    document.getElementById('btn-redo').addEventListener('click', redo);
    document.getElementById('btn-sort').addEventListener('click', sortDeck);
    document.getElementById('btn-shuffle').addEventListener('click', shuffleDeck);
    document.getElementById('btn-clear').addEventListener('click', requestClearDeck);

    // Quick jump pills
    document.querySelectorAll('.jump-pill').forEach(btn => {
        btn.addEventListener('click', () => {
            const target = document.getElementById(btn.dataset.jump);
            if (target) target.scrollIntoView({ behavior: 'smooth', block: 'start' });
        });
    });

    // Search, filters & pagination
    document.getElementById('search-input').addEventListener('input', scheduleSearch);
    document.getElementById('btn-search-clear').addEventListener('click', () => {
        const input = document.getElementById('search-input');
        input.value = '';
        document.getElementById('btn-search-clear').hidden = true;
        document.getElementById('search-kbd-hint').hidden = false;
        handleSearch();
        input.focus();
    });
    document.getElementById('filter-frame').addEventListener('change', handleSearch);
    document.getElementById('filter-attribute').addEventListener('change', handleSearch);
    document.getElementById('sort-results').addEventListener('change', handleSearch);
    document.getElementById('btn-page-prev').addEventListener('click', () => changePage(-1));
    document.getElementById('btn-page-next').addEventListener('click', () => changePage(1));

    // Hand Simulator
    document.getElementById('btn-draw-new-hand').addEventListener('click', drawNewHand);
    document.getElementById('btn-draw-extra').addEventListener('click', drawExtraCard);

    // Import / Export
    document.getElementById('btn-export-ydk').addEventListener('click', exportYdk);
    document.getElementById('btn-export-json').addEventListener('click', exportJson);
    document.getElementById('btn-copy-text').addEventListener('click', copyDecklistText);
    document.getElementById('import-file-input').addEventListener('change', (e) => {
        const file = e.target.files && e.target.files[0];
        if (!file) return;
        file.text().then(txt => importDeckContent(txt, file.name));
        e.target.value = '';
    });
    document.getElementById('btn-import-paste').addEventListener('click', () => {
        const text = document.getElementById('import-paste-area').value;
        importDeckContent(text);
    });

    // Save Manager
    document.getElementById('upload-save-input').addEventListener('change', (e) => {
        const file = e.target.files && e.target.files[0];
        if (file) handleSaveUpload(file);
        e.target.value = '';
    });
    document.getElementById('btn-download-save').addEventListener('click', () => {
        if (!state.backendAvailable) return;
        window.location.href = '/api/download_save';
    });

    // Settings
    document.getElementById('toggle-art-cache').addEventListener('change', (e) => {
        toggleArtCacheSetting(e.target.checked);
    });
    document.getElementById('btn-sync-descriptions').addEventListener('click', syncDescriptionsLocally);
    document.getElementById('toggle-auto-unlock').addEventListener('change', (e) => {
        state.autoUnlock = e.target.checked;
    });

    // Global Keyboard Shortcuts
    document.addEventListener('keydown', (e) => {
        const tag = (e.target && e.target.tagName) ? e.target.tagName.toLowerCase() : '';
        const isTyping = tag === 'input' || tag === 'textarea' || tag === 'select';

        if (e.key === 'Escape') {
            if (anyModalOpen()) {
                closeAllModals();
            } else if (state.pinnedCard) {
                unpinCard();
            } else if (isTyping) {
                e.target.blur();
            }
            return;
        }

        if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') {
            e.preventDefault();
            saveDeck(false);
            return;
        }

        if ((e.ctrlKey || e.metaKey) && !isTyping) {
            if (e.key.toLowerCase() === 'z' && !e.shiftKey) {
                e.preventDefault();
                undo();
                return;
            }
            if (e.key.toLowerCase() === 'y' || (e.key.toLowerCase() === 'z' && e.shiftKey)) {
                e.preventDefault();
                redo();
                return;
            }
        }

        if (e.key === '/' && !isTyping && !anyModalOpen()) {
            e.preventDefault();
            const search = document.getElementById('search-input');
            search.focus();
            search.select();
        }
    });
}

async function init() {
    bindEvents();

    try {
        const dbRes = await fetch('cards_db.json');
        if (!dbRes.ok) throw new Error(`Failed to load cards_db.json (${dbRes.status})`);
        const rawDb = await dbRes.json();

        state.cardsDb = rawDb.filter(c => c && typeof c.name === 'string' && c.name.trim().length > 0);
        state.cardsByIndex.clear();
        state.cardsByPasscode.clear();

        for (const c of state.cardsDb) {
            if (typeof c.game_index === 'number') {
                state.cardsByIndex.set(c.game_index, c);
            }
            if (isValidArtPasscode(c.passcode)) {
                const stripped = String(parseInt(c.passcode, 10));
                if (!state.cardsByPasscode.has(c.passcode)) state.cardsByPasscode.set(c.passcode, c);
                if (!state.cardsByPasscode.has(stripped)) state.cardsByPasscode.set(stripped, c);
            }
        }

        handleSearch();
    } catch (err) {
        console.error('Database load error:', err);
        showToast('Failed to load cards_db.json. Ensure server is running.', 'error');
        return;
    }

    // Probe local Python backend; cleanly fall back to static Demo Mode if absent
    let backendStatus = null;
    try {
        const statusRes = await fetch('/api/status', { cache: 'no-store' });
        if (statusRes.ok) {
            const ct = statusRes.headers.get('content-type') || '';
            if (ct.includes('application/json')) {
                backendStatus = await statusRes.json();
            }
        }
    } catch (_) {
        backendStatus = null;
    }

    if (backendStatus) {
        state.backendAvailable = true;
        await loadCardDescriptions();
        applyServerStatus(backendStatus);

        try {
            const deckRes = await fetch('/api/deck', { cache: 'no-store' });
            if (deckRes.ok) {
                const deckData = await deckRes.json();
                loadDeckData(deckData, true);
                return;
            }
        } catch (err) {
            console.error('Backend deck fetch error:', err);
        }
    }

    // Pure Static Fallback (GitHub Pages / file server without Python)
    state.backendAvailable = false;
    applyServerStatus({ mode: 'static', encrypted: false, backups: [] });

    try {
        const savedStatic = localStorage.getItem(STATIC_STORAGE_KEY);
        if (savedStatic) {
            loadDeckData(JSON.parse(savedStatic), true);
            return;
        }
    } catch (_) {
        // Ignore corrupt localStorage
    }

    try {
        const sampleRes = await fetch('sample_deck.json');
        if (sampleRes.ok) {
            const sampleData = await sampleRes.json();
            loadDeckData(sampleData, true);
            return;
        }
    } catch (_) {
        // Ignore missing sample_deck.json
    }

    loadDeckData({ name: 'New Deck', main: [], side: [], extra: [] }, true);
}

window.addEventListener('DOMContentLoaded', init);
