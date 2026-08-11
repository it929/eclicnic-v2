// Function to print receipt
function printReceipt(receiptNumber) {
    console.log('Printing receipt:', receiptNumber);
    
    const receiptContent = document.getElementById(`receipt-content-${receiptNumber}`);
    
    if (!receiptContent) {
        Swal.fire({
            icon: 'error',
            title: 'Error!',
            text: 'Receipt content not found.'
        });
        return;
    }
    
    const contentClone = receiptContent.cloneNode(true);
    
    const printWindow = window.open('', '_blank');
    
    printWindow.document.write(`
        <!DOCTYPE html>
        <html>
            <head>
                <title>Receipt #${receiptNumber}</title>
                <meta charset="UTF-8">
                <link rel="stylesheet" href="https://stackpath.bootstrapcdn.com/bootstrap/4.5.2/css/bootstrap.min.css">
                <style>
                    body { 
                        padding: 20px; 
                        font-family: Arial, sans-serif;
                        background-color: #fff;
                    }
                    .receipt-wrapper { 
                        max-width: 800px; 
                        margin: 0 auto; 
                        border: 1px solid #ddd;
                        padding: 20px;
                    }
                    .receipt-header { 
                        text-align: center; 
                        margin-bottom: 20px;
                        padding: 20px;
                        border-bottom: 1px solid #eee;
                    }
                    .receipt-meta { 
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
                    }
                    .patient-details-col { 
                        flex: 1; 
                    }
                    .receipt-title {
                        text-align: center;
                        margin: 30px 0;
                        font-size: 18px;
                        font-weight: bold;
                    }
                    .receipt-table { 
                        width: 100%; 
                        border-collapse: collapse; 
                    }
                    .receipt-table th, 
                    .receipt-table td { 
                        border: 1px solid #ddd; 
                        padding: 8px; 
                        text-align: left;
                    }
                    .receipt-table th { 
                        background-color: #f2f2f2;
                    }
                    .receipt-totals {
                        margin: 20px;
                        display: flex;
                        justify-content: flex-end;
                    }
                    .receipt-totals div {
                        width: 600px;
                        border: 1px solid #ddd;
                        padding: 10px 15px;
                        background-color: #fdfdfd;
                    }
                    .rt{
                        width: 250px;
                    }
                    .receipt-totals table {
                        width: 100%;
                        margin: 0;
                        border: none;
                    }
                    .receipt-totals td {
                        border: none;
                        padding: 5px;
                    }
                    .receipt-totals td:first-child {
                        font-weight: bold;
                        width: 150px;
                    }
                    .receipt-totals td:last-child {
                        text-align: right;
                    }
                    .text-success {
                        color: #28a745;
                    }
                    .btn-toolbar, .btn-group, .dropdown, button {
                        display: none !important;
                    }
                    .remarks-box {
                        margin: 20px;
                        padding: 10px;
                        border: 1px solid #ddd;
                        background-color: #f9f9f9;
                    }
                    .payment-info {
                        margin: 10px 20px;
                        padding: 10px;
                        border-left: 3px solid #28a745;
                        background-color: #f9f9f9;
                    }
                    * {
                        -webkit-print-color-adjust: exact;
                        print-color-adjust: exact;
                    }
                    @media print {
                        .text-success {
                            color: #28a745 !important;
                        }
                    }
                </style>
            </head>
            <body>
                ${contentClone.outerHTML}
                <script>
                    window.onload = function() {
                        setTimeout(function() {
                            window.print();
                            setTimeout(function() { window.close(); }, 500);
                        }, 500);
                    };
                </script>
            </body>
        </html>
    `);
    
    printWindow.document.close();
}

// Function to add signature to receipt
function addReceiptSignature(receiptNumber) {
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
                    <button type="button" class="btn btn-sm btn-secondary" onclick="clearReceiptSignature()">
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
                initializeReceiptSignaturePad();
            }, 100);
        },
        preConfirm: () => {
            const canvas = document.getElementById('signature-pad');
            const signatureData = canvas.toDataURL('image/png');
            
            const ctx = canvas.getContext('2d');
            const pixelData = ctx.getImageData(0, 0, canvas.width, canvas.height).data;
            const isSignatureEmpty = pixelData.every(pixel => pixel === 0);
            
            if (isSignatureEmpty) {
                Swal.showValidationMessage('Please provide your signature');
                return false;
            }
            
            return { signerName: currentUserFullName, signatureData };
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
            
            const receiptContent = document.getElementById(`receipt-content-${receiptNumber}`);
            if (receiptContent) {
                receiptContent.innerHTML += signatureHtml;
            }
            
            saveReceiptSignature(receiptNumber, result.value.signerName, result.value.signatureData);
            
            Swal.fire('Success!', 'Signature added successfully.', 'success');
        }
    });
}

// Function to initialize signature pad
function initializeReceiptSignaturePad() {
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
function clearReceiptSignature() {
    const canvas = document.getElementById('signature-pad');
    if (canvas) {
        const ctx = canvas.getContext('2d');
        ctx.clearRect(0, 0, canvas.width, canvas.height);
    }
}

// Function to save signature
function saveReceiptSignature(receiptNumber, signerName, signatureData) {
    fetch('/save-receipt-signature/', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCookie('csrftoken')
        },
        body: JSON.stringify({
            receipt_number: receiptNumber,
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

// Function to email QR code for receipt
function emailReceiptQRCode(receiptNumber) {
    const receiptElement = document.getElementById(`receipt-content-${receiptNumber}`);
    const patientEmail = receiptElement ? receiptElement.dataset.patientEmail : '';
    
    if (!patientEmail) {
        Swal.fire({
            icon: 'error',
            title: 'Error!',
            text: 'Patient email address not found.'
        });
        return;
    }
    
    const totalElement = receiptElement ? receiptElement.querySelector('.receipt-totals span') : null;
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
                        Receipt: ${receiptNumber}<br>
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
            
            generateAndSendReceiptQRCode(receiptNumber, patientEmail);
        }
    });
}

// Function to send QR code via email
function generateAndSendReceiptQRCode(receiptNumber, email) {
    fetch('/send-receipt-qr-code/', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCookie('csrftoken')
        },
        body: JSON.stringify({
            receipt_number: receiptNumber,
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

// Function to download receipt
function downloadReceipt(receiptNumber, format) {
    Swal.fire({
        title: 'Generating ' + format.toUpperCase(),
        html: 'Please wait while we prepare your document...',
        timer: 3000,
        timerProgressBar: true,
        didOpen: () => {
            Swal.showLoading();
            window.location.href = `/download-receipt/${receiptNumber}/${format}/?patient_id=${document.body.dataset.patientId}`;
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