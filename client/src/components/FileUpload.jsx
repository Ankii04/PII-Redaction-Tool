import React, { useRef, useState } from 'react';
import { UploadCloud, FileText, ArrowRight } from 'lucide-react';

export default function FileUpload({ onFileSelected, isProcessing }) {
  const [isDragOver, setIsDragOver] = useState(false);
  const [selectedFile, setSelectedFile] = useState(null);
  const fileInputRef = useRef(null);

  const handleDragOver = (e) => {
    e.preventDefault();
    setIsDragOver(true);
  };

  const handleDragLeave = () => {
    setIsDragOver(false);
  };

  const handleDrop = (e) => {
    e.preventDefault();
    setIsDragOver(false);
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      const file = e.dataTransfer.files[0];
      if (file.name.toLowerCase().endsWith('.docx')) {
        setSelectedFile(file);
      } else {
        alert('Please upload a Microsoft Word (.docx) document.');
      }
    }
  };

  const handleFileInput = (e) => {
    if (e.target.files && e.target.files.length > 0) {
      const file = e.target.files[0];
      setSelectedFile(file);
    }
  };

  const handleSubmit = (e) => {
    e.stopPropagation();
    if (selectedFile && !isProcessing) {
      onFileSelected(selectedFile);
    }
  };

  return (
    <div 
      className={`dropzone ${isDragOver ? 'active' : ''}`}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
      onClick={() => fileInputRef.current?.click()}
    >
      <input 
        type="file" 
        ref={fileInputRef} 
        onChange={handleFileInput} 
        accept=".docx,application/vnd.openxmlformats-officedocument.wordprocessingml.document" 
        style={{ display: 'none' }} 
      />

      <div className="dropzone-icon">
        <UploadCloud size={32} />
      </div>

      <h3 className="dropzone-title">
        {selectedFile ? 'Document Selected' : 'Upload Prospectus or Word Document (.docx)'}
      </h3>
      <p className="dropzone-desc">
        Drag & drop your `.docx` file here, or click to browse. The document structure, tables, and formatting will be strictly preserved.
      </p>

      {selectedFile && (
        <div style={{ marginTop: '1rem', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '1rem' }}>
          <div className="file-pill">
            <FileText size={16} />
            <span>{selectedFile.name} ({(selectedFile.size / 1024 / 1024).toFixed(2)} MB)</span>
          </div>

          <button 
            type="button"
            className="btn btn-primary"
            onClick={handleSubmit}
            disabled={isProcessing}
            style={{ padding: '0.75rem 2rem', fontSize: '1rem' }}
          >
            {isProcessing ? 'Analyzing & Redacting PII...' : 'Redact Document Now'}
            <ArrowRight size={18} />
          </button>
        </div>
      )}
    </div>
  );
}
