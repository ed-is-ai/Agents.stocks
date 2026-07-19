// One global refresh binding controls the sole top-level Refresh Data button.
(function () {
  const refreshButton = document.getElementById('refresh-data-button');
  if (!refreshButton) return;

  function setRunning(running) {
    refreshButton.disabled = running;
    refreshButton.classList.toggle('loading', running);
  }

  document.body.addEventListener('htmx:beforeRequest', (event) => {
    if (event.detail.elt === refreshButton) setRunning(true);
  });

  document.body.addEventListener('htmx:afterRequest', (event) => {
    if (event.detail.elt === refreshButton) setRunning(false);
  });

  document.body.addEventListener('htmx:afterSwap', (event) => {
    if (event.detail.target.id !== 'pipeline-status') return;
    const state = event.detail.target.querySelector('[data-pipeline-state]')?.dataset.pipelineState;
    setRunning(state === 'running');
  });

  document.body.addEventListener('htmx:responseError', (event) => {
    if (event.detail.elt === refreshButton) setRunning(false);
  });
})();
