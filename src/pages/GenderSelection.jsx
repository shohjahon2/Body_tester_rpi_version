import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import Button from '../components/Button';
import '../styles/pages/_gender-selection.scss';

const GenderSelection = () => {
  const navigate = useNavigate();
  // Kiosk API: yuz orqali taniqli bemor (patientId bor, hali ro'yxatdan
  // o'tkazilishi kerak bo'lgan pendingEmbedding yo'q) — jinsi allaqachon
  // backendda bor, qayta so'ralmaydi. Lazy init — birinchi renderdayoq
  // aniq, tugmalar bir lahza ham ko'rinmaydi.
  const [isKnownPatient] = useState(
    () => Boolean(localStorage.getItem('patientId')) && !localStorage.getItem('pendingEmbedding')
  );

  // Sessiyani boshlash (eski sensor qiymatlarini tozalash) va tanlangan
  // o'lchov(lar)ga navigatsiya — jins tanlangandan keyin ham, taniqli
  // bemor uchun darhol ham shu funksiya ishlatiladi.
  const proceedToMeasurement = async () => {
    try {
      await fetch('http://localhost:8000/session/start', { method: 'POST' });
    } catch (err) {
      console.warn('Sessiyani boshlab bo\'lmadi:', err);
    }

    // Check if we're in "all measurements" mode
    const isAllMeasurementsMode = localStorage.getItem('isAllMeasurementsMode') === 'true';

    if (isAllMeasurementsMode) {
      // Get the first measurement from the queue
      const measurementQueue = JSON.parse(localStorage.getItem('measurementQueue') || '[]');
      const currentIndex = parseInt(localStorage.getItem('currentMeasurementIndex') || '0');

      if (measurementQueue.length > 0 && currentIndex < measurementQueue.length) {
        const firstMeasurement = measurementQueue[currentIndex];
        navigate(`/measurement/${firstMeasurement}`);
      } else {
        navigate('/success');
      }
    } else {
      // Single measurement mode - get selected measurement type from localStorage
      const selectedMeasurement = localStorage.getItem('selectedMeasurement');

      // Navigate to the appropriate measurement page
      if (selectedMeasurement === 'temperature') {
        navigate('/measurement/temperature');
      } else if (selectedMeasurement === 'weight-height') {
        navigate('/measurement/weight-height');
      } else if (selectedMeasurement === 'oxygen') {
        navigate('/measurement/oxygen');
      } else if (selectedMeasurement === 'blood-pressure') {
        navigate('/measurement/blood-pressure');
      } else {
        // Default to temperature if no selection
        navigate('/measurement/temperature');
      }
    }
  };

  useEffect(() => {
    if (isKnownPatient) {
      proceedToMeasurement();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isKnownPatient]);

  const handleGenderSelect = async (gender) => {
    // Store gender selection
    localStorage.setItem('gender', gender);

    // Kiosk API: yangi bemor uchun, tug'ilgan sana+jins ma'lum bo'lgani
    // uchun ro'yxatdan o'tkazish (enroll). Yosh yuborilmaydi — server
    // birth_date'dan o'zi hisoblaydi (hujjat, 7-bo'lim).
    const userData = JSON.parse(localStorage.getItem('userData') || '{}');
    const pendingEmbeddingRaw = localStorage.getItem('pendingEmbedding');

    if (!userData.isGuest && pendingEmbeddingRaw) {
      try {
        const pending = JSON.parse(pendingEmbeddingRaw);
        const birthDate = localStorage.getItem('birthDate') || undefined;
        const res = await fetch('http://localhost:8000/face/enroll', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            embedding: pending.embedding,
            quality_score: pending.quality_score,
            first_name: userData.name,
            gender: gender === 'male' ? 'M' : 'F',
            birth_date: birthDate,
          }),
        });
        const result = await res.json();
        if (result.status === 'enrolled') {
          localStorage.setItem('patientId', String(result.patient_id));
          localStorage.removeItem('pendingEmbedding');
        } else {
          console.warn('Ro\'yxatdan o\'tkazish natijasi:', result.status, result.detail || '');
        }
      } catch (err) {
        console.warn('Ro\'yxatdan o\'tkazib bo\'lmadi:', err);
      }
    }

    await proceedToMeasurement();
  };

  if (isKnownPatient) {
    return null;
  }

  return (
    <div className="gender-selection">
      <div className="gender-selection__container">
        <div className="gender-selection__content">
          <h2 className="gender-selection__title">Iltimos jinsni tanlang</h2>
          
          <img 
            src="/assets/imgs/gender.webp" 
            alt="Gender symbols" 
            className="gender-selection__image"
          />
          
          <div className="gender-selection__buttons">
            <Button 
              onClick={() => handleGenderSelect('female')} 
              className="gender-selection__button"
            >
              Ayol
            </Button>
            <Button 
              onClick={() => handleGenderSelect('male')} 
              className="gender-selection__button"
            >
              Erkak
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
};

export default GenderSelection;
