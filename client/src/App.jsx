import React, { useState } from 'react';
import Header from './components/Header.jsx';
import FileUpload from './components/FileUpload.jsx';
import StatsGrid from './components/StatsGrid.jsx';
import DetectionsTable from './components/DetectionsTable.jsx';
import EvaluationModal from './components/EvaluationModal.jsx';
import { Shield, Sparkles, CheckCircle2, AlertCircle } from 'lucide-react';

export default function App() {
  const [isProcessing, setIsProcessing] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [processingMessage, setProcessingMessage] = useState('');
  const [isMetricsOpen, setIsMetricsOpen] = useState(false);

  const readJsonResponse = async (response) => {
    const text = await response.text();
    try {
      return JSON.parse(text);
    } catch {
      if (!response.ok) {
        throw new Error(`Server returned HTTP ${response.status} (${response.statusText || 'Error'}).`);
      }
      throw new Error('Invalid response from server.');
    }
  };

  const waitForJob = async (statusUrl) => {
    const deadline = Date.now() + 10 * 60 * 1000;

    while (Date.now() < deadline) {
      await new Promise(resolve => setTimeout(resolve, 3000));

      const response = await fetch(statusUrl, { cache: 'no-store' });
      const data = await readJsonResponse(response);

      if (!response.ok || !data.success) {
        throw new Error(data.error || 'Could not read redaction job status.');
      }

      if (data.message) {
        setProcessingMessage(data.message);
      }

      if (data.status === 'complete') {
        if (!data.result?.success) {
          throw new Error(data.result?.error || 'Redaction job completed without a valid result.');
        }
        return data.result;
      }

      if (data.status === 'error') {
        throw new Error(data.error || 'Failed to redact document.');
      }
    }

    throw new Error('Redaction is taking too long. Please try again with a smaller document.');
  };

  const handleFileProcess = async (file) => {
    setIsProcessing(true);
    setError(null);
    setResult(null);
    setProcessingMessage('Uploading document...');

    const formData = new FormData();
    formData.append('file', file);

    try {
      const response = await fetch('/api/redact', {
        method: 'POST',
        body: formData,
      });

      const data = await readJsonResponse(response);

      if (!response.ok || !data.success) {
        throw new Error(data.error || data.details || 'Failed to redact document.');
      }

      if (data.accepted && data.statusUrl) {
        setProcessingMessage('Document uploaded. Redaction job queued...');
        const completedResult = await waitForJob(data.statusUrl);
        setResult(completedResult);
      } else {
        setResult(data);
      }
    } catch (err) {
      console.error('Error during redaction:', err);
      setError(err.message || 'An unexpected error occurred during processing.');
    } finally {
      setIsProcessing(false);
      setProcessingMessage('');
    }
  };

  const handleReset = () => {
    setResult(null);
    setError(null);
  };

  return (
    <div className="container">
      <Header onOpenMetrics={() => setIsMetricsOpen(true)} />

      {error && (
        <div style={{
          background: 'rgba(239, 68, 68, 0.15)',
          border: '1px solid rgba(239, 68, 68, 0.4)',
          borderRadius: '10px',
          padding: '1rem 1.25rem',
          color: '#fca5a5',
          display: 'flex',
          alignItems: 'center',
          gap: '0.75rem',
          marginBottom: '2rem'
        }}>
          <AlertCircle size={20} />
          <div>
            <strong>Processing Error:</strong> {error}
          </div>
        </div>
      )}

      {isProcessing && (
        <div className="processing-card">
          <div className="spinner"></div>
          <h3 style={{ fontSize: '1.25rem', fontWeight: '600', marginBottom: '0.5rem' }}>
            Presidio Hybrid Pipeline Running...
          </h3>
          <p style={{ color: 'var(--text-secondary)', fontSize: '0.875rem', maxWidth: '520px', margin: '0 auto' }}>
            {processingMessage || 'Extracting paragraphs, table cells, and section headers with run-level offset mapping, running NER & custom regex recognizers, and resolving entity overlaps.'}
          </p>
        </div>
      )}

      {!isProcessing && !result && (
        <>
          <FileUpload onFileSelected={handleFileProcess} isProcessing={isProcessing} />

          <div style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))',
            gap: '1.5rem',
            marginTop: '3rem'
          }}>
            <div className="stat-card" style={{ flexDirection: 'column', alignItems: 'flex-start' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', fontWeight: '600', color: '#60a5fa' }}>
                <Shield size={18} />
                <span>9 Required PII Types</span>
              </div>
              <p style={{ fontSize: '0.825rem', color: 'var(--text-secondary)', marginTop: '0.5rem' }}>
                Emails, Indian & International Phones, Full Names, Companies, Addresses, SSNs, Credit Cards (Luhn), DOBs, and IPs.
              </p>
            </div>

            <div className="stat-card" style={{ flexDirection: 'column', alignItems: 'flex-start' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', fontWeight: '600', color: '#34d399' }}>
                <Sparkles size={18} />
                <span>Format-Preserving</span>
              </div>
              <p style={{ fontSize: '0.825rem', color: 'var(--text-secondary)', marginTop: '0.5rem' }}>
                Run-level surgery preserves all bold, italic, tables, and section headers without converting to plain text.
              </p>
            </div>

            <div className="stat-card" style={{ flexDirection: 'column', alignItems: 'flex-start' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', fontWeight: '600', color: '#fbbf24' }}>
                <CheckCircle2 size={18} />
                <span>False-Positive Guard</span>
              </div>
              <p style={{ fontSize: '0.825rem', color: 'var(--text-secondary)', marginTop: '0.5rem' }}>
                Financial amounts (₹5,000M), page numbers, years (FY 2024-25), and generic references are never redacted.
              </p>
            </div>
          </div>
        </>
      )}

      {!isProcessing && result && (
        <div>
          <StatsGrid 
            stats={result.stats} 
            totalPii={result.totalPii}
            unitsWithPii={result.unitsWithPii}
            totalUnits={result.totalUnits}
          />

          <DetectionsTable 
            detections={result.sampleDetections}
            downloadUrl={result.downloadUrl}
            originalName={result.originalName}
            onReset={handleReset}
          />
        </div>
      )}

      <EvaluationModal 
        isOpen={isMetricsOpen} 
        onClose={() => setIsMetricsOpen(false)} 
      />
    </div>
  );
}
