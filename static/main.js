// Toggle sidebar visibility
function toggleSidebar() {
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

// Confirmation for deleting a feeding time
function confirmDelete(time) {
    return confirm(`Delete the ${time} feeding?`);
}

// Confirmation for changing portion size
function confirmChange(message) {
    return confirm(message);
}

// Confirmation for manual feeding
function confirmFeed(form) {
    const portion = form.querySelector('select[name="portion"]').value;
    return confirm(`Dispense a ${portion} portion now?`);
}

// Close sidebar on escape key
document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
        const sidebar = document.querySelector('.sidebar');
        if (sidebar.classList.contains('active')) {
            toggleSidebar();
        }
    }
});

// Close sidebar when clicking outside on mobile
document.addEventListener('click', (e) => {
    const sidebar = document.querySelector('.sidebar');
    const settingsToggle = document.querySelector('.settings-toggle');
    
    if (sidebar.classList.contains('active') && 
        !sidebar.contains(e.target) && 
        !settingsToggle.contains(e.target)) {
        toggleSidebar();
    }
});
