import React, { useEffect, useState } from 'react';
import { X, CheckCircle, AlertTriangle, FileCode } from 'lucide-react';

export default function EvaluationModal({ isOpen, onClose }) {
  const [metrics, setMetrics] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (isOpen) {
      fetch('/api/evaluation')
        .then(res => res.json())
        .then(data => {
          setMetrics(data.metrics);
          setLoading(false);
        })
        .catch(err => {
          console.error('Failed to load metrics:', err);
          setLoading(false);
        });
    }
  }, [isOpen]);

  if (!isOpen) return null;

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-content" onClick={e => e.stopPropagation()}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1.25rem' }}>
          <h2 style={{ fontSize: '1.25rem', fontWeight: '700' }}>Evaluation Strategy & Metrics</h2>
          <button 
            onClick={onClose} 
            style={{ background: 'transparent', border: 'none', color: 'var(--text-secondary)', cursor: 'pointer' }}
          >
            <X size={20} />
          </button>
        </div>

        <p style={{ fontSize: '0.875rem', color: 'var(--text-secondary)', marginBottom: '1rem' }}>
          Calculated by evaluating detections against an independently curated ground truth dataset (<code>ground_truth/ground_truth.json</code>) matching spans at ≥50% overlap.
        </p>

        {loading ? (
          <div style={{ textAlign: 'center', padding: '2rem' }}>Loading evaluation metrics...</div>
        ) : metrics ? (
          <>
            <table className="metrics-table">
              <thead>
                <tr>
                  <th>Entity Type</th>
                  <th>TP</th>
                  <th>FP</th>
                  <th>FN</th>
                  <th>Precision</th>
                  <th>Recall</th>
                  <th>F1 Score</th>
                </tr>
              </thead>
              <tbody>
                {metrics.perType && Object.entries(metrics.perType).map(([type, m]) => (
                  <tr key={type}>
                    <td><strong>{type}</strong></td>
                    <td>{m.tp}</td>
                    <td>{m.fp}</td>
                    <td>{m.fn}</td>
                    <td style={{ color: m.precision === 1 ? 'var(--accent-success)' : 'inherit' }}>
                      {(m.precision * 100).toFixed(1)}%
                    </td>
                    <td>{(m.recall * 100).toFixed(1)}%</td>
                    <td style={{ fontWeight: '600' }}>{(m.f1 * 100).toFixed(1)}%</td>
                  </tr>
                ))}
                {metrics.overall && (
                  <tr style={{ background: 'rgba(37, 99, 235, 0.15)', fontWeight: '700' }}>
                    <td>OVERALL (GT Sample)</td>
                    <td>{metrics.overall.tp}</td>
                    <td>{metrics.overall.fp}</td>
                    <td>{metrics.overall.fn}</td>
                    <td style={{ color: 'var(--accent-success)' }}>
                      {(metrics.overall.precision * 100).toFixed(1)}%
                    </td>
                    <td>{(metrics.overall.recall * 100).toFixed(1)}%</td>
                    <td style={{ color: '#60a5fa' }}>
                      {(metrics.overall.f1 * 100).toFixed(1)}%
                    </td>
                  </tr>
                )}
              </tbody>
            </table>

            {metrics.absentTypes && (
              <div style={{ marginTop: '1.5rem', background: 'var(--bg-input)', padding: '1rem', borderRadius: '8px', fontSize: '0.8rem' }}>
                <div style={{ fontWeight: '600', marginBottom: '0.5rem', color: '#f59e0b' }}>
                  Entities Absent from Document:
                </div>
                <ul style={{ paddingLeft: '1.25rem', color: 'var(--text-secondary)' }}>
                  {Object.entries(metrics.absentTypes).map(([type, desc]) => (
                    <li key={type} style={{ marginBottom: '0.25rem' }}>
                      <strong>{type}</strong>: {desc}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </>
        ) : null}

        <div style={{ marginTop: '1.5rem', textAlign: 'right' }}>
          <button className="btn btn-outline" onClick={onClose}>
            Close
          </button>
        </div>
      </div>
    </div>
  );
}
