/* Enables decorative motion styles; remove the class if the motion script never loads. */
(function () {
  'use strict';
  document.documentElement.classList.add('js');
  window.setTimeout(function () {
    if (!window.__motionReady) document.documentElement.classList.remove('js');
  }, 3000);
})();
