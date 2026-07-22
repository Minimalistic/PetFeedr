// ===== Dark Mode =====
const darkQuery = window.matchMedia('(prefers-color-scheme: dark)');

function getEffectiveTheme(mode) {
    if (mode === 'light' || mode === 'dark') return mode;
    return darkQuery.matches ? 'dark' : 'light';
}

function setThemeMode(mode) {
    localStorage.setItem('petfeedr-theme', mode);
    document.documentElement.setAttribute('data-theme', getEffectiveTheme(mode));
    document.querySelectorAll('.theme-opt').forEach(btn => {
        const active = btn.dataset.mode === mode;
        btn.classList.toggle('active', active);
        btn.setAttribute('aria-checked', active);
    });
}

// Apply before DOM ready to prevent flash
(function initTheme() {
    const mode = localStorage.getItem('petfeedr-theme') || 'auto';
    document.documentElement.setAttribute('data-theme', getEffectiveTheme(mode));
})();

// Follow system changes in auto mode
darkQuery.addEventListener('change', () => {
    const mode = localStorage.getItem('petfeedr-theme') || 'auto';
    if (mode === 'auto') {
        document.documentElement.setAttribute('data-theme', getEffectiveTheme('auto'));
    }
});

function initThemePicker() {
    const mode = localStorage.getItem('petfeedr-theme') || 'auto';
    document.querySelectorAll('.theme-opt').forEach(btn => {
        const active = btn.dataset.mode === mode;
        btn.classList.toggle('active', active);
        btn.setAttribute('aria-checked', active);
        btn.addEventListener('click', () => setThemeMode(btn.dataset.mode));
    });
}

// ===== Timeline =====
function initTimeline() {
    const timeline = document.querySelector('.timeline');
    const nowEl = document.getElementById('timeline-now');
    if (!timeline || !nowEl) return;

    const start = parseInt(timeline.dataset.start);
    const end = parseInt(timeline.dataset.end);

    function updateNow() {
        const d = new Date();
        const mins = d.getHours() * 60 + d.getMinutes();
        const pct = ((mins - start) / (end - start)) * 100;
        if (pct < 0 || pct > 100) {
            nowEl.style.display = 'none';
        } else {
            nowEl.style.display = '';
            nowEl.style.left = pct + '%';
        }
    }
    updateNow();
    setInterval(updateNow, 60000);

    // Tap to toggle tooltip on mobile
    document.querySelectorAll('.timeline-dot').forEach(dot => {
        dot.addEventListener('click', () => {
            document.querySelectorAll('.timeline-dot.active').forEach(d => {
                if (d !== dot) d.classList.remove('active');
            });
            dot.classList.toggle('active');
        });
    });
}

// ===== Consumption Rate Toggle =====
function initRateToggle() {
    const btns = document.querySelectorAll('.rate-btn');
    const value = document.getElementById('rate-value');
    if (!btns.length || !value || !window._consumption) return;

    const c = window._consumption;
    const labels = {
        daily: `${c.daily_cups} cups (${c.daily_lbs} lbs)`,
        weekly: `${c.weekly_cups} cups (${c.weekly_lbs} lbs)`,
        monthly: `${c.monthly_cups} cups (${c.monthly_lbs} lbs)`
    };

    btns.forEach(btn => {
        btn.addEventListener('click', () => {
            btns.forEach(b => {
                b.classList.remove('active');
                b.setAttribute('aria-checked', 'false');
            });
            btn.classList.add('active');
            btn.setAttribute('aria-checked', 'true');
            value.textContent = labels[btn.dataset.period];
        });
    });
}

// ===== Bar Chart Day Detail =====
function initBarChart() {
    const columns = document.querySelectorAll('.bar-column[data-date]');
    const panel = document.getElementById('day-detail');
    if (!columns.length || !panel) return;

    columns.forEach(col => {
        col.addEventListener('click', async () => {
            const date = col.dataset.date;
            const wasSelected = col.classList.contains('selected');

            columns.forEach(c => c.classList.remove('selected'));

            if (wasSelected) {
                panel.style.display = 'none';
                return;
            }

            col.classList.add('selected');
            panel.style.display = '';
            panel.innerHTML = '<div style="text-align:center;color:var(--color-text-muted);">Loading...</div>';

            try {
                const resp = await fetch(`/api/day-detail/${date}`);
                const data = await resp.json();
                if (!data.success || data.feedings.length === 0) {
                    panel.innerHTML = '<div style="text-align:center;color:var(--color-text-muted);">No feedings recorded</div>';
                    return;
                }

                const dateObj = new Date(date + 'T12:00:00');
                const dayName = dateObj.toLocaleDateString('en-US', { weekday: 'long', month: 'short', day: 'numeric' });

                let html = `<div class="day-detail-header">
                    <span>${dayName}</span>
                    <span class="day-detail-total">${data.total_cups} cups &middot; ${data.total_feedings} feedings</span>
                </div><ul class="day-detail-list">`;

                for (const f of data.feedings) {
                    html += `<li class="day-detail-item">
                        <span class="day-detail-time">${f.time}</span>
                        <span class="day-detail-portion portion-${f.portion}" title="${f.cups} cups">${f.portion}<span class="detail-cups">${f.cups} cup${f.cups !== 1 ? 's' : ''}</span></span>
                        <span class="day-detail-type">${f.type}</span>
                    </li>`;
                }
                html += '</ul>';
                panel.innerHTML = html;
            } catch {
                panel.innerHTML = '<div style="text-align:center;color:var(--color-text-muted);">Failed to load</div>';
            }
        });
    });
}

// Update icon and init features once DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    initThemePicker();
    initCountdown();
    initTimeline();
    initBarChart();
    initRateToggle();
    initAjaxForms();

    // Register service worker for PWA
    if ('serviceWorker' in navigator) {
        navigator.serviceWorker.register('/sw.js', { scope: '/' });
    }
});

// ===== Layout =====
// Large desktop breakpoint - sidebar is always visible
const LG_BREAKPOINT = 1400;
const lgQuery = window.matchMedia(`(min-width: ${LG_BREAKPOINT}px)`);

// Toggle sidebar visibility
function toggleSidebar() {
    // Sidebar is always visible on large desktop — no-op
    if (lgQuery.matches) return;

    const sidebar = document.querySelector('.sidebar');
    const overlay = document.querySelector('.sidebar-overlay');

    sidebar.classList.toggle('active');
    overlay.classList.toggle('active');

    // Prevent body scroll when sidebar is open
    if (sidebar.classList.contains('active')) {
        document.body.style.overflow = 'hidden';
    } else {
        document.body.style.overflow = '';
    }
}

// Open sidebar and focus the add-feeding form
function openAddFeeding() {
    const sidebar = document.querySelector('.sidebar');
    if (!sidebar) return;

    // Open sidebar if it's not already visible
    if (!lgQuery.matches && !sidebar.classList.contains('active')) {
        toggleSidebar();
    }

    // Wait for sidebar transition to finish before focusing
    setTimeout(() => {
        const timeInput = document.getElementById('feeding_time');
        if (timeInput) {
            timeInput.focus();
            // Scroll the sidebar content to show the form
            const sidebarContent = document.querySelector('.sidebar-content');
            if (sidebarContent) sidebarContent.scrollTop = 0;
        }
        const form = document.querySelector('.add-form');
        if (form) {
            form.classList.add('highlight');
            setTimeout(() => form.classList.remove('highlight'), 1500);
        }
    }, 400); // matches sidebar transition duration (0.35s)
}

// Clean up sidebar state when crossing into large desktop
lgQuery.addEventListener('change', (e) => {
    if (e.matches) {
        document.querySelector('.sidebar').classList.remove('active');
        document.querySelector('.sidebar-overlay').classList.remove('active');
        document.body.style.overflow = '';
    }
});

// ===== Toasts =====
function showToast(message, type = 'info', duration = 3500) {
    const container = document.getElementById('toast-container');
    if (!container) return;
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.textContent = message;
    container.appendChild(toast);
    setTimeout(() => {
        toast.classList.add('removing');
        toast.addEventListener('animationend', () => toast.remove());
    }, duration);
}

// ===== Inline Confirm =====
function confirmAction(button, onConfirm) {
    if (button.dataset.confirming === 'true') {
        clearTimeout(Number(button.dataset.confirmTimer));
        delete button.dataset.confirming;
        button.classList.remove('confirming');
        onConfirm();
        return;
    }
    const origHTML = button.innerHTML;
    const origClass = button.className;
    button.dataset.confirming = 'true';
    button.innerHTML = 'Sure?';
    button.classList.add('confirming');
    const timer = setTimeout(() => {
        button.innerHTML = origHTML;
        button.className = origClass;
        delete button.dataset.confirming;
    }, 3000);
    button.dataset.confirmTimer = timer;
}

// ===== AJAX Form Submission =====
async function submitForm(form) {
    const url = form.action;
    const formData = new FormData(form);
    try {
        const response = await fetch(url, {
            method: 'POST',
            body: formData,
            headers: { 'Accept': 'application/json' }
        });
        const data = await response.json();
        if (data.success) {
            showToast(data.message, 'success');
            setTimeout(() => window.location.reload(), 500);
        } else {
            showToast(data.message || 'Something went wrong', 'error');
        }
    } catch (err) {
        showToast('Network error — please try again', 'error');
    }
}

function initAjaxForms() {
    // Add feeding form
    document.querySelector('.add-form')?.addEventListener('submit', function(e) {
        e.preventDefault();
        submitForm(this);
    });

    // Feed now — with inline confirm on circle button
    const feedForm = document.querySelector('.feed-form');
    feedForm?.addEventListener('submit', function(e) {
        e.preventDefault();
        const btn = this.querySelector('.feed-circle-btn');
        if (!btn) return;
        confirmAction(btn, () => {
            submitForm(this).then(() => {
                // Ripple + pulse effect
                const ripple = document.createElement('span');
                ripple.className = 'ripple';
                btn.appendChild(ripple);
                btn.classList.add('fed');
                ripple.addEventListener('animationend', () => ripple.remove());
                setTimeout(() => btn.classList.remove('fed'), 1000);
            });
        });
    });

    // Portion segmented control description
    document.querySelectorAll('.portion-segmented input').forEach(radio => {
        radio.addEventListener('change', () => {
            const desc = document.getElementById('portion-desc');
            if (desc && typeof portionDescriptions !== 'undefined') {
                desc.textContent = portionDescriptions[radio.value] || '';
            }
        });
        // Init the selected one
        if (radio.checked) radio.dispatchEvent(new Event('change'));
    });

    // Delete forms — with inline confirm
    document.querySelectorAll('form[action="/delete"]').forEach(form => {
        form.addEventListener('submit', function(e) {
            e.preventDefault();
            const btn = this.querySelector('.btn-delete');
            confirmAction(btn, () => submitForm(this));
        });
    });

    // Portion change (auto-submit on select change)
    document.querySelectorAll('form[action="/update_portion"]').forEach(form => {
        form.querySelector('select')?.addEventListener('change', () => submitForm(form));
        form.addEventListener('submit', e => e.preventDefault());
    });

    // Toggle fixed (no confirmation needed)
    document.querySelectorAll('form[action="/toggle_fixed"]').forEach(form => {
        form.addEventListener('submit', function(e) {
            e.preventDefault();
            submitForm(this);
        });
    });

    // Hopper refill — reveal the estimate form, then AJAX submit
    const refillToggle = document.getElementById('refill-toggle');
    const refillForm = document.querySelector('.refill-form');
    if (refillToggle && refillForm) {
        refillToggle.addEventListener('click', () => {
            refillForm.hidden = !refillForm.hidden;
        });
        refillForm.addEventListener('submit', function(e) {
            e.preventDefault();
            submitForm(this);
        });
    }
}

// ===== Countdown Timer =====
function initCountdown() {
    const card = document.querySelector('.next-feeding-card');
    const nextTime = card?.dataset.nextFeeding;
    if (!nextTime) return;

    let countdownEl = document.getElementById('feeding-countdown');
    if (!countdownEl) {
        countdownEl = document.createElement('div');
        countdownEl.id = 'feeding-countdown';
        countdownEl.className = 'feeding-countdown';
        const timeEl = card.querySelector('.next-feeding-time');
        if (timeEl) timeEl.after(countdownEl);
    }

    let lastText = '';

    function tick() {
        const now = new Date();
        const [h, m] = nextTime.split(':').map(Number);
        const target = new Date(now);
        target.setHours(h, m, 0, 0);
        if (target <= now) target.setDate(target.getDate() + 1);

        const diffMin = Math.floor((target - now) / 60000);
        const hours = Math.floor(diffMin / 60);
        const mins = diffMin % 60;

        let newText;
        if (hours > 0) {
            newText = `in ${hours}h ${mins}m`;
        } else if (mins > 0) {
            newText = `in ${mins}m`;
        } else {
            newText = 'any moment now';
        }

        if (newText !== lastText) {
            countdownEl.classList.add('updating');
            setTimeout(() => {
                countdownEl.textContent = newText;
                countdownEl.classList.remove('updating');
            }, 150);
            lastText = newText;
        }
    }

    tick();
    setInterval(tick, 1000);
}

// Auto-refresh every 60s (skip if user is interacting with a form)
setInterval(() => {
    const tag = document.activeElement?.tagName;
    if (tag === 'INPUT' || tag === 'SELECT' || tag === 'TEXTAREA') return;
    window.location.reload();
}, 60000);

// Close sidebar on escape key
document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && !lgQuery.matches) {
        const sidebar = document.querySelector('.sidebar');
        if (sidebar.classList.contains('active')) {
            toggleSidebar();
        }
    }
});

// Close sidebar when clicking outside on mobile/tablet
document.addEventListener('click', (e) => {
    if (lgQuery.matches) return;

    const sidebar = document.querySelector('.sidebar');
    const settingsToggle = document.querySelector('.settings-toggle');

    if (sidebar.classList.contains('active') &&
        !sidebar.contains(e.target) &&
        !settingsToggle.contains(e.target)) {
        toggleSidebar();
    }
});
