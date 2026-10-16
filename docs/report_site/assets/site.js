(() => {
  const sidebar = document.getElementById('sidebar');
  const toggle = document.getElementById('menu-toggle');
  const search = document.getElementById('nav-search');
  if (!sidebar || !toggle || !search) return;

  toggle.addEventListener('click', () => {
    const open = sidebar.classList.toggle('open');
    toggle.setAttribute('aria-expanded', String(open));
  });

  sidebar.querySelectorAll('a').forEach(link => link.addEventListener('click', () => {
    sidebar.classList.remove('open');
    toggle.setAttribute('aria-expanded', 'false');
  }));

  search.addEventListener('input', () => {
    const query = search.value.toLocaleLowerCase().trim();
    sidebar.querySelectorAll('.nav-home, .nav-link').forEach(link => {
      link.classList.toggle('hidden', Boolean(query) && !link.textContent.toLocaleLowerCase().includes(query));
    });
    sidebar.querySelectorAll('.nav-group').forEach(group => {
      group.classList.toggle('hidden', !group.querySelector('.nav-link:not(.hidden)'));
    });
  });

  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && sidebar.classList.contains('open')) {
      sidebar.classList.remove('open');
      toggle.setAttribute('aria-expanded', 'false');
      toggle.focus();
    }
  });
})();
