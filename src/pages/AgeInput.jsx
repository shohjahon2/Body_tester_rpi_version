import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import Button from '../components/Button';
import '../styles/pages/_age-input.scss';

// Kiosk API: yosh endi serverga yuborilmaydi — u tug'ilgan sanadan
// serverning o'zi hisoblaydi (tug'ilgan kun o'tgan-o'tmaganini ham
// hisobga olib). Shuning uchun kalendardan ANIQ sana olinadi, ISO 8601
// ko'rinishida ("1992-05-17"). Kelajakdagi sana va 120 yoshdan katta
// sana server tomonidan rad etiladi — shu chegaralar kalendarda ham
// qo'yiladi (min/max).
const toIsoDate = (date) => date.toISOString().slice(0, 10);
const todayIso = () => toIsoDate(new Date());
const minIsoDate = () => {
  const d = new Date();
  d.setFullYear(d.getFullYear() - 120);
  return toIsoDate(d);
};

const AgeInput = () => {
  const navigate = useNavigate();
  const [birthDate, setBirthDate] = useState('');
  const [error, setError] = useState('');

  useEffect(() => {
    // Kiosk API: yuz orqali taniqli bemor (patientId bor, hali
    // ro'yxatdan o'tkazilishi kerak bo'lgan pendingEmbedding yo'q) —
    // tug'ilgan sanasi allaqachon backendda bor, qayta so'ralmaydi.
    const known = localStorage.getItem('patientId') && !localStorage.getItem('pendingEmbedding');
    if (known) {
      navigate('/selection', { replace: true });
    }
  }, [navigate]);

  const handleDateChange = (e) => {
    setBirthDate(e.target.value);
    setError('');
  };

  const handleNext = () => {
    if (!birthDate) {
      setError("Iltimos, tug'ilgan sanangizni tanlang");
      return;
    }
    localStorage.setItem('birthDate', birthDate);
    navigate('/selection');
  };

  return (
    <div className="age-input">
      <div className="age-input__container">
        <div className="age-input__content">
          <h2 className="age-input__title">Iltimos tug'ilgan sanangizni kiriting</h2>

          <div className="age-input__controls">
            <input
              type="date"
              className="age-input__display"
              value={birthDate}
              onChange={handleDateChange}
              min={minIsoDate()}
              max={todayIso()}
              aria-label="Tug'ilgan sanangizni tanlang"
            />
          </div>

          {error && <p className="age-input__error">{error}</p>}

          <div className="age-input__next-wrapper">
            <Button onClick={handleNext} className="age-input__next-button">
              Keyingisi
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
};

export default AgeInput;
