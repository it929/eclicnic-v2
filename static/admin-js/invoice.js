// Function to print invoice
// Function to print invoice - FIXED VERSION
function printInvoice(invoiceNumber) {
    console.log('Printing invoice:', invoiceNumber);
    
    // Get the invoice content div directly by its ID
    const invoiceContent = document.getElementById(`invoice-content-${invoiceNumber}`);
    
    if (!invoiceContent) {
        console.error('Invoice content not found for ID:', `invoice-content-${invoiceNumber}`);
        Swal.fire({
            icon: 'error',
            title: 'Error!',
            text: 'Invoice content not found.'
        });
        return;
    }
    
    console.log('Invoice content found, length:', invoiceContent.innerHTML.length);
    console.log('Table rows:', invoiceContent.querySelectorAll('.invoice-table tbody tr').length);
    
    // Clone the content to avoid modifying the original
    const contentClone = invoiceContent.cloneNode(true);
    
    // Create a new window for printing
    const printWindow = window.open('', '_blank');
    
    // Get all styles from the original document
    const styles = document.querySelectorAll('style, link[rel="stylesheet"]');
    let stylesHTML = '';
    styles.forEach(style => {
        if (style.tagName === 'STYLE') {
            stylesHTML += style.outerHTML;
        } else if (style.tagName === 'LINK' && style.rel === 'stylesheet') {
            stylesHTML += style.outerHTML;
        }
    });
    
    // Add Bootstrap and Font Awesome explicitly
    stylesHTML += `
        <link rel="stylesheet" href="https://stackpath.bootstrapcdn.com/bootstrap/4.5.2/css/bootstrap.min.css">
        <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/5.15.4/css/all.min.css">
    `;
    
    printWindow.document.write(`
        <!DOCTYPE html>
        <html>
            <head>
                <title>Invoice #${invoiceNumber}</title>
                <meta charset="UTF-8">
                <meta name="viewport" content="width=device-width, initial-scale=1.0">
                ${stylesHTML}
                <style>
                    body { 
                        padding: 20px; 
                        font-family: Arial, sans-serif;
                        background-color: #fff;
                    }
                    .invoice-wrapper { 
                        max-width: 800px; 
                        margin: 0 auto; 
                        border: 1px solid #ddd;
                        box-shadow: none;
                        background-color: #fff;
                        padding: 20px;
                    }
                    .invoice-header { 
                        text-align: center; 
                        margin-bottom: 20px;
                        padding: 20px;
                        border-bottom: 1px solid #eee;
                    }
                    .invoice-meta { 
                        text-align: right; 
                        margin-bottom: 20px;
                        padding: 10px 20px;
                        border-bottom: 1px solid #eee;
                    }
                    .patient-details-box { 
                        border: 1px solid #ddd; 
                        padding: 15px; 
                        margin: 20px;
                        display: flex;
                        background-color: #fff;
                    }
                    .patient-details-col { 
                        flex: 1; 
                    }
                    .invoice-title {
                        text-align: center;
                        margin: 30px 0;
                        font-size: 18px;
                        font-weight: bold;
                        color: #333;
                    }
                    .invoice-table-section {
                        padding: 0 20px;
                        margin-bottom: 20px;
                    }
                    .invoice-table { 
                        width: 100%; 
                        border-collapse: collapse; 
                    }
                    .invoice-table th, 
                    .invoice-table td { 
                        border: 1px solid #ddd; 
                        padding: 8px; 
                        text-align: left;
                        font-size: 12px;
                    }
                    .invoice-table th { 
                        background-color: #f2f2f2 !important;
                        -webkit-print-color-adjust: exact;
                        print-color-adjust: exact;
                    }
                    .invoice-totals { 
                        display: flex; 
                        justify-content: flex-end; 
                        margin: 20px;
                    }
                    .invoice-totals div { 
                        width: 300px; 
                        border: 1px solid #ddd; 
                        padding: 10px; 
                        background-color: #fdfdfd;
                    }
                    /* Hide any buttons or interactive elements */
                    .btn-toolbar, 
                    .btn-group, 
                    .dropdown,
                    .modal-footer,
                    button {
                        display: none !important;
                    }
                    /* Ensure borders and colors print */
                    * {
                        -webkit-print-color-adjust: exact;
                        print-color-adjust: exact;
                    }
                </style>
            </head>
            <body>
                ${contentClone.outerHTML}
                <script>
                    // Auto-print when ready
                    window.onload = function() {
                        setTimeout(function() {
                            window.print();
                            setTimeout(function() {
                                window.close();
                            }, 500);
                        }, 500);
                    };
                </script>
            </body>
        </html>
    `);
    
    printWindow.document.close();
}

// Function to add signature
function addSignature(invoiceNumber) {
    console.log('Adding signature for:', invoiceNumber); // Debug log
    
    const currentUserFullName = document.body.dataset.userFullname || 'System User';
    
    Swal.fire({
        title: 'Add Digital Signature',
        html: `
            <div style="text-align: left;">
                <div class="form-group mb-3">
                    <label>Signing as:</label>
                    <input type="text" class="form-control" value="${currentUserFullName}" readonly disabled style="background-color: #f8f9fa;">
                    <small class="text-muted">You are signing as the currently logged-in user</small>
                </div>
                <div class="form-group mb-3">
                    <label>Draw your signature:</label>
                    <canvas id="signature-pad" style="border: 2px solid #ccc; width: 100%; height: 200px; border-radius: 5px; cursor: crosshair;"></canvas>
                </div>
                <div style="text-align: center; margin-top: 10px;">
                    <button type="button" class="btn btn-sm btn-secondary" onclick="clearSignature()">
                        <i class="fas fa-eraser"></i> Clear Signature
                    </button>
                </div>
            </div>
        `,
        showCancelButton: true,
        confirmButtonText: 'Add Signature',
        confirmButtonColor: '#28a745',
        cancelButtonText: 'Cancel',
        width: '600px',
        didOpen: () => {
            setTimeout(() => {
                initializeSignaturePad();
            }, 100);
        },
        preConfirm: () => {
            const canvas = document.getElementById('signature-pad');
            if (!canvas) return false;
            
            const signatureData = canvas.toDataURL('image/png');
            
            const ctx = canvas.getContext('2d');
            const pixelData = ctx.getImageData(0, 0, canvas.width, canvas.height).data;
            const isSignatureEmpty = pixelData.every(pixel => pixel === 0);
            
            if (isSignatureEmpty) {
                Swal.showValidationMessage('Please provide your signature');
                return false;
            }
            
            return { 
                signerName: currentUserFullName, 
                signatureData 
            };
        }
    }).then((result) => {
        if (result.isConfirmed) {
            const signatureHtml = `
                <div style="margin-top: 30px; padding: 20px; border-top: 2px solid #333; text-align: right;">
                    <div style="margin-bottom: 10px;">
                        <img src="${result.value.signatureData}" style="max-height: 60px; margin-bottom: 10px;" alt="Signature">
                    </div>
                    <p style="margin: 0; font-weight: bold;">Digitally Signed by: ${result.value.signerName}</p>
                    <p style="margin: 0;">Date: ${new Date().toLocaleDateString('en-US', { year: 'numeric', month: 'long', day: 'numeric' })}</p>
                </div>
            `;
            
            const invoiceContent = document.querySelector(`#invoiceModal${invoiceNumber} .invoice-wrapper`);
            if (invoiceContent) {
                invoiceContent.innerHTML += signatureHtml;
            }
            
            saveSignature(invoiceNumber, result.value.signerName, result.value.signatureData);
            
            Swal.fire('Success!', 'Signature added successfully.', 'success');
        }
    });
}

// Function to initialize signature pad
function initializeSignaturePad() {
    const canvas = document.getElementById('signature-pad');
    if (!canvas) return;
    
    canvas.width = canvas.offsetWidth;
    canvas.height = canvas.offsetHeight;
    
    const ctx = canvas.getContext('2d');
    ctx.strokeStyle = '#000';
    ctx.lineWidth = 2;
    ctx.lineCap = 'round';
    ctx.lineJoin = 'round';
    
    let drawing = false;
    let lastX = 0;
    let lastY = 0;
    
    canvas.addEventListener('mousedown', startDrawing);
    canvas.addEventListener('mousemove', draw);
    canvas.addEventListener('mouseup', stopDrawing);
    canvas.addEventListener('mouseleave', stopDrawing);
    
    canvas.addEventListener('touchstart', handleTouchStart);
    canvas.addEventListener('touchmove', handleTouchMove);
    canvas.addEventListener('touchend', stopDrawing);
    
    function startDrawing(e) {
        drawing = true;
        const rect = canvas.getBoundingClientRect();
        lastX = e.clientX - rect.left;
        lastY = e.clientY - rect.top;
        ctx.beginPath();
        ctx.moveTo(lastX, lastY);
    }
    
    function draw(e) {
        if (!drawing) return;
        e.preventDefault();
        
        const rect = canvas.getBoundingClientRect();
        const x = e.clientX - rect.left;
        const y = e.clientY - rect.top;
        
        ctx.lineTo(x, y);
        ctx.stroke();
        ctx.beginPath();
        ctx.moveTo(x, y);
    }
    
    function handleTouchStart(e) {
        e.preventDefault();
        drawing = true;
        const rect = canvas.getBoundingClientRect();
        const touch = e.touches[0];
        lastX = touch.clientX - rect.left;
        lastY = touch.clientY - rect.top;
        ctx.beginPath();
        ctx.moveTo(lastX, lastY);
    }
    
    function handleTouchMove(e) {
        e.preventDefault();
        if (!drawing) return;
        
        const rect = canvas.getBoundingClientRect();
        const touch = e.touches[0];
        const x = touch.clientX - rect.left;
        const y = touch.clientY - rect.top;
        
        ctx.lineTo(x, y);
        ctx.stroke();
        ctx.beginPath();
        ctx.moveTo(x, y);
    }
    
    function stopDrawing() {
        drawing = false;
        ctx.beginPath();
    }
}

// Function to clear signature
function clearSignature() {
    const canvas = document.getElementById('signature-pad');
    if (canvas) {
        const ctx = canvas.getContext('2d');
        ctx.clearRect(0, 0, canvas.width, canvas.height);
    }
}

// Function to email QR code
function emailQRCode(invoiceNumber) {
    console.log('Emailing QR code for:', invoiceNumber); // Debug log
    
    const invoiceElement = document.querySelector(`#invoiceModal${invoiceNumber} .invoice-wrapper`);
    const patientEmail = invoiceElement ? invoiceElement.dataset.patientEmail : '';
    
    if (!patientEmail) {
        Swal.fire({
            icon: 'error',
            title: 'Error!',
            text: 'Patient email address not found.'
        });
        return;
    }
    
    const totalElement = invoiceElement ? invoiceElement.querySelector('.invoice-totals span') : null;
    const totalAmount = totalElement ? totalElement.textContent : '0.00';
    
    Swal.fire({
        title: 'Send QR Code',
        html: `
            <div style="text-align: left;">
                <div class="form-group mb-3">
                    <label>Sending to:</label>
                    <input type="email" class="form-control" value="${patientEmail}" readonly disabled style="background-color: #f8f9fa;">
                    <small class="text-muted">QR code will be sent to the patient's registered email</small>
                </div>
                <div style="margin-top: 20px; text-align: center; padding: 15px; background: #f8f9fa; border-radius: 10px;" id="qr-code-container">
                    <div style="margin-bottom: 10px;">QR Code Preview</div>
                    <div style="background: white; padding: 15px; display: inline-block; border: 1px solid #ddd;">
                        <div style="width: 128px; height: 128px; background: linear-gradient(45deg, #000 25%, #fff 25%, #fff 50%, #000 50%, #000 75%, #fff 75%, #fff 100%); background-size: 32px 32px;"></div>
                    </div>
                    <div style="margin-top: 10px; font-size: 12px; color: #666;">
                        Invoice: ${invoiceNumber}<br>
                        Amount: ${totalAmount}
                    </div>
                </div>
            </div>
        `,
        showCancelButton: true,
        confirmButtonText: 'Send Email',
        confirmButtonColor: '#28a745',
        cancelButtonText: 'Cancel',
        width: '500px',
        preConfirm: () => {
            return { email: patientEmail };
        }
    }).then((result) => {
        if (result.isConfirmed) {
            Swal.fire({
                title: 'Sending...',
                text: 'Please wait while we send the QR code',
                allowOutsideClick: false,
                didOpen: () => {
                    Swal.showLoading();
                }
            });
            
            generateAndSendQRCode(invoiceNumber, patientEmail);
        }
    });
}

// Function to send QR code via email
function generateAndSendQRCode(invoiceNumber, email) {
    fetch('/send-qr-code/', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCookie('csrftoken')
        },
        body: JSON.stringify({
            invoice_number: invoiceNumber,
            email: email
        })
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            Swal.fire({
                icon: 'success',
                title: 'Success!',
                text: 'QR Code sent to ' + email,
                timer: 3000,
                showConfirmButton: false
            });
        } else {
            Swal.fire({
                icon: 'error',
                title: 'Error!',
                text: data.message || 'Failed to send QR Code'
            });
        }
    })
    .catch(error => {
        Swal.fire({
            icon: 'error',
            title: 'Error!',
            text: 'Failed to send QR Code. Please try again.'
        });
        console.error('Error:', error);
    });
}

// Function to save signature to database
function saveSignature(invoiceNumber, signerName, signatureData) {
    fetch('/save-signature/', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCookie('csrftoken')
        },
        body: JSON.stringify({
            invoice_number: invoiceNumber,
            signer_name: signerName,
            signature_data: signatureData
        })
    })
    .then(response => response.json())
    .then(data => {
        console.log('Signature saved:', data);
    })
    .catch(error => {
        console.error('Error saving signature:', error);
    });
}

// Function to download invoice
function downloadInvoice(invoiceNumber, format) {
    console.log('Downloading invoice:', invoiceNumber, 'as', format); // Debug log
    
    Swal.fire({
        title: 'Generating ' + format.toUpperCase(),
        html: 'Please wait while we prepare your document...',
        timer: 3000,
        timerProgressBar: true,
        didOpen: () => {
            Swal.showLoading();
            window.location.href = `/download-invoice/${invoiceNumber}/${format}/`;
        }
    }).then((result) => {
        if (result.dismiss === Swal.DismissReason.timer) {
            Swal.fire({
                icon: 'success',
                title: 'Download Started',
                text: 'Your ' + format.toUpperCase() + ' file is being downloaded',
                timer: 1500,
                showConfirmButton: false
            });
        }
    });
}

// Utility function to get CSRF token
function getCookie(name) {
    let cookieValue = null;
    if (document.cookie && document.cookie !== '') {
        const cookies = document.cookie.split(';');
        for (let i = 0; i < cookies.length; i++) {
            const cookie = cookies[i].trim();
            if (cookie.substring(0, name.length + 1) === (name + '=')) {
                cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                break;
            }
        }
    }
    return cookieValue;
}

// Debug: Log that scripts are loaded
console.log('Invoice functions loaded:', {
    printInvoice: typeof printInvoice,
    addSignature: typeof addSignature,
    emailQRCode: typeof emailQRCode,
    downloadInvoice: typeof downloadInvoice
});

