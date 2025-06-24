document.addEventListener('DOMContentLoaded', function() {
    // Инициализация всплывающих подсказок
    const tooltips = document.querySelectorAll('[data-tooltip]');
    
    tooltips.forEach(tooltip => {
        tooltip.addEventListener('mouseenter', showTooltip);
        tooltip.addEventListener('mouseleave', hideTooltip);
    });
    
    function showTooltip(e) {
        const tooltipText = this.getAttribute('data-tooltip');
        const tooltipEl = document.createElement('div');
        
        tooltipEl.className = 'absolute bg-gray-800 text-white px-2 py-1 rounded text-sm z-50';
        tooltipEl.textContent = tooltipText;
        tooltipEl.style.top = `${e.clientY + 10}px`;
        tooltipEl.style.left = `${e.clientX + 10}px`;
        
        document.body.appendChild(tooltipEl);
        this.tooltipElement = tooltipEl;
    }
    
    function hideTooltip() {
        if (this.tooltipElement) {
            this.tooltipElement.remove();
        }
    }
    
    // Обработка форм
    const forms = document.querySelectorAll('form');
    
    forms.forEach(form => {
        form.addEventListener('submit', function(e) {
            const submitBtn = this.querySelector('button[type="submit"]');
            
            if (submitBtn) {
                submitBtn.disabled = true;
                submitBtn.innerHTML = '<i class="fas fa-spinner fa-spin mr-2"></i> Обработка...';
            }
        });
    });
});