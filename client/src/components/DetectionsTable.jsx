import React, { useState } from 'react';
import { Download, FileCheck, Search } from 'lucide-react';

export default function DetectionsTable({ detections = [], downloadUrl, originalName, onReset }) {
  const [filterType, setFilterType] = useState('ALL');
  const [searchQuery, setSearchQuery] = useState('');

  const entityTypes = ['ALL', ...Array.from(new Set(detections.map(d => d.entity_type)))];

  const filtered = detections.filter(d => {
    const matchesType = filterType === 'ALL' || d.entity_type === filterType;
    const matchesSearch = !searchQuery || 
      d.text.toLowerCase().includes(searchQuery.toLowerCase()) || 
      d.unit_id.toLowerCase().includes(searchQuery.toLowerCase());
    return matchesType && matchesSearch;
  });

  const getBadgeClass = (type) => {
    switch (type) {
      case 'EMAIL_ADDRESS': return 'badge badge-email';
      case 'PHONE_NUMBER': return 'badge badge-phone';
      case 'PERSON': return 'badge badge-person';
      case 'ORGANIZATION': return 'badge badge-org';
      case 'ADDRESS': return 'badge badge-address';
      default: return 'badge';
    }
  };

  return (
    <div className="summary-card">
      <div className="card-header">
        <div>
          <div className="card-title" style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <FileCheck size={20} color="var(--accent-success)" />
            <span>Redaction Complete: {originalName}</span>
          </div>
          <div style={{ fontSize: '0.825rem', color: 'var(--text-secondary)', marginTop: '0.25rem' }}>
            All detected entities have been sanitized with type-specific replacement tags.
          </div>
        </div>

        <div style={{ display: 'flex', gap: '0.75rem' }}>
          <button className="btn btn-outline" onClick={onReset}>
            Upload Another
          </button>
          <a href={downloadUrl} className="btn btn-primary" download>
            <Download size={16} />
            Download Redacted DOCX
          </a>
        </div>
      </div>

      <div style={{ display: 'flex', gap: '1rem', marginBottom: '1.25rem', flexWrap: 'wrap' }}>
        <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
          {entityTypes.map(t => (
            <button
              key={t}
              onClick={() => setFilterType(t)}
              style={{
                background: filterType === t ? 'var(--accent-primary)' : 'var(--bg-input)',
                color: filterType === t ? 'white' : 'var(--text-secondary)',
                border: '1px solid var(--border-color)',
                borderRadius: '6px',
                padding: '0.35rem 0.75rem',
                fontSize: '0.8rem',
                cursor: 'pointer',
                fontFamily: 'var(--font-mono)'
              }}
            >
              {t}
            </button>
          ))}
        </div>
      </div>

      <div style={{ maxHeight: '420px', overflowY: 'auto', border: '1px solid var(--border-color)', borderRadius: '8px' }}>
        <table className="detection-table">
          <thead>
            <tr>
              <th style={{ width: '18%' }}>Entity Type</th>
              <th style={{ width: '45%' }}>Sanitized Text Match</th>
              <th style={{ width: '25%' }}>Document Location ID</th>
              <th style={{ width: '12%', textAlign: 'right' }}>Confidence</th>
            </tr>
          </thead>
          <tbody>
            {filtered.length > 0 ? (
              filtered.map((d, i) => (
                <tr key={i}>
                  <td>
                    <span className={getBadgeClass(d.entity_type)}>
                      {d.entity_type}
                    </span>
                  </td>
                  <td style={{ fontFamily: 'var(--font-mono)', fontSize: '0.825rem' }}>
                    "{d.text}"
                  </td>
                  <td style={{ color: 'var(--text-muted)', fontSize: '0.8rem', fontFamily: 'var(--font-mono)' }}>
                    {d.unit_id}
                  </td>
                  <td style={{ textAlign: 'right', fontFamily: 'var(--font-mono)', color: 'var(--accent-success)' }}>
                    {(d.score * 100).toFixed(0)}%
                  </td>
                </tr>
              ))
            ) : (
              <tr>
                <td colSpan="4" style={{ textAlign: 'center', color: 'var(--text-muted)', padding: '2rem' }}>
                  No detections matching the selected filter.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
