

        document.addEventListener('DOMContentLoaded', function () {

            document.querySelectorAll('.tooltip-row').forEach(el => {

                let data;
                try {
                    data = JSON.parse(el.dataset.tooltip);
                } catch (e) {
                    console.error('Invalid tooltip JSON', e, el.dataset.tooltip);
                    return;
                }

                const content = `
                    <div class="tooltip-card">
                        <div class="tooltip-title">Prescription Note</div>
                        <div><strong>Doctor:</strong> ${data.doctor}</div>
                        <div><strong>Notes:</strong> ${data.notes || '-'}</div>
                        <div><strong>Date:</strong> ${data.date}</div>
                    </div>
                `;

                tippy(el, {
                    content: content,
                    allowHTML: true,
                    animation: 'shift-away',
                    theme: 'light-border',
                    placement: 'right',
                    interactive: true,
                    delay: [150, 100],
                    maxWidth: 350,
                });
            });

        });
