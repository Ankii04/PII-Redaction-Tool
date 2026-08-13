import React from 'react';
import { Mail, Phone, User, Building2, MapPin, ShieldAlert, Hash } from 'lucide-react';

export default function StatsGrid({ stats = {}, totalPii = 0, unitsWithPii = 0, totalUnits = 0 }) {
  const cards = [
    {
      label: 'Total PII Redacted',
      value: totalPii,
      icon: <ShieldAlert size={24} color="#60a5fa" />,
      bg: 'rgba(37, 99, 235, 0.12)'
    },
    {
      label: 'Email Addresses',
      value: stats.EMAIL_ADDRESS || 0,
      icon: <Mail size={24} color="#60a5fa" />,
      bg: 'rgba(59, 130, 246, 0.12)'
    },
    {
      label: 'Phone Numbers',
      value: stats.PHONE_NUMBER || 0,
      icon: <Phone size={24} color="#34d399" />,
      bg: 'rgba(16, 185, 129, 0.12)'
    },
    {
      label: 'Person Names',
      value: stats.PERSON || 0,
      icon: <User size={24} color="#fbbf24" />,
      bg: 'rgba(245, 158, 11, 0.12)'
    },
    {
      label: 'Organizations',
      value: stats.ORGANIZATION || 0,
      icon: <Building2 size={24} color="#a78bfa" />,
      bg: 'rgba(139, 92, 246, 0.12)'
    },
    {
      label: 'Addresses',
      value: stats.ADDRESS || 0,
      icon: <MapPin size={24} color="#f472b6" />,
      bg: 'rgba(236, 72, 153, 0.12)'
    }
  ];

  return (
    <div>
      <div className="stats-grid">
        {cards.map((c, idx) => (
          <div key={idx} className="stat-card">
            <div className="stat-icon-wrapper" style={{ background: c.bg }}>
              {c.icon}
            </div>
            <div>
              <div className="stat-value">{c.value}</div>
              <div className="stat-label">{c.label}</div>
            </div>
          </div>
        ))}
      </div>

      <div style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', textAlign: 'right', marginTop: '-0.5rem', marginBottom: '1.5rem' }}>
        Found PII across <strong>{unitsWithPii}</strong> of <strong>{totalUnits}</strong> content units (paragraphs, cells, headers).
      </div>
    </div>
  );
}
