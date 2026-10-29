'use strict';
// Links only: no remote scripts, embeds or requests until the user follows a link.
window.wowheadLink = function (text, type, id) {
  const kinds = new Set(['item', 'npc', 'quest', 'spell', 'object', 'faction', 'skill']);
  const value = Number(id);
  const valid = kinds.has(type) && Number.isSafeInteger(value) && value > 0 && value <= 4294967295;
  const node = document.createElement(valid ? 'a' : 'span');
  node.textContent = text;
  if (valid) {
    node.href = 'https://www.wowhead.com/wotlk/' + type + '=' + value;
    node.target = '_blank';
    node.rel = 'noopener noreferrer';
    node.className = 'wowhead-link';
    node.title = 'View ' + text + ' on Wowhead WotLK (opens in a new tab)';
    node.addEventListener('click', event => event.stopPropagation());
  }
  return node;
};

// Quest names navigate locally; the separate arrow always opens the external database.
window.questLinks = function (text, id) {
  const value = Number(id), group = document.createElement('span');
  if (!Number.isSafeInteger(value) || value <= 0 || value > 4294967295) { group.textContent = text; return group; }
  const local = document.createElement('a');
  local.textContent = text;
  local.href = '/quest-log?mode=all&q=' + value + '&id=' + value;
  local.className = 'dashboard-record-link';
  local.addEventListener('click', event => event.stopPropagation());
  const external = wowheadLink('↗', 'quest', value);
  external.classList.add('wowhead-shortcut');
  external.setAttribute('aria-label', 'View ' + text + ' on Wowhead');
  group.append(local, external);
  return group;
};
