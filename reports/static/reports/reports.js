(function () {
  'use strict';

  function bindPrint() {
    var button = document.getElementById('report-print');
    if (button) {
      button.addEventListener('click', function () {
        window.print();
      });
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', bindPrint);
  } else {
    bindPrint();
  }
}());
