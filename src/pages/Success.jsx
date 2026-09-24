import React, { useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { FaCheck } from 'react-icons/fa';
import Button from '../components/Button';
import '../styles/pages/_success.scss';

const Success = () => {
  const navigate = useNavigate();

  useEffect(() => {
    // Collect all entered data
    const userData = JSON.parse(localStorage.getItem('userData') || '{}');
    const birthDate = localStorage.getItem('birthDate');
    const gender = localStorage.getItem('gender');
    const temperature = localStorage.getItem('temperature');
    const weight = localStorage.getItem('weight');
    const height = localStorage.getItem('height');
    const oxygen = localStorage.getItem('oxygen');
    const bloodPressureSystolic = localStorage.getItem('bloodPressureSystolic');
    const bloodPressureDiastolic = localStorage.getItem('bloodPressureDiastolic');
    const pulse = localStorage.getItem('pulse');

    // Compile all data
    const allData = {
      registration: {
        isGuest: userData.isGuest || false,
        name: userData.name || 'N/A',
        photo: userData.photo ? 'Photo captured' : null
      },
      personalInfo: {
        birthDate: birthDate || 'N/A',
        gender: gender || 'N/A'
      },
      measurements: {
        temperature: temperature ? `${temperature}°C` : 'N/A',
        weight: weight ? `${weight}kg` : 'N/A',
        height: height ? `${height}sm` : 'N/A',
        oxygen: oxygen ? `${oxygen}%` : 'N/A',
        bloodPressure: (bloodPressureSystolic && bloodPressureDiastolic) 
          ? `${bloodPressureSystolic}/${bloodPressureDiastolic} mmHg` 
          : 'N/A',
        pulse: pulse ? `${pulse} bpm` : 'N/A'
      },
      timestamp: new Date().toISOString()
    };

    // Log all data to console
    console.log('========================================');
    console.log('BODY TESTER - BARCHA MA\'LUMOTLAR');
    console.log('========================================');
    console.log('Ro\'yxatdan o\'tish:', allData.registration);
    console.log('Shaxsiy ma\'lumotlar:', allData.personalInfo);
    console.log('O\'lchovlar:', allData.measurements);
    console.log('Vaqt:', allData.timestamp);
    console.log('========================================');
    console.log('To\'liq ma\'lumotlar:', JSON.stringify(allData, null, 2));
    console.log('========================================');

    // Kiosk API: agar bemor identify/enroll orqali aniqlangan bo'lsa,
    // yig'ilgan o'lchovlarni clinic backendga yuborish.
    const patientId = localStorage.getItem('patientId');
    if (!userData.isGuest && patientId) {
      fetch('http://localhost:8000/submit', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ patient_id: Number(patientId) }),
      })
        .then(res => res.json())
        .then(result => console.log('Backendga yuborish natijasi:', result))
        .catch(err => console.warn('Backendga yuborib bo\'lmadi:', err));
    }
  }, []);

  const handleHome = () => {
    // Clear all data when going home
    localStorage.removeItem('userData');
    localStorage.removeItem('birthDate');
    localStorage.removeItem('gender');
    localStorage.removeItem('temperature');
    localStorage.removeItem('weight');
    localStorage.removeItem('height');
    localStorage.removeItem('oxygen');
    localStorage.removeItem('bloodPressureSystolic');
    localStorage.removeItem('bloodPressureDiastolic');
    localStorage.removeItem('pulse');
    localStorage.removeItem('selectedMeasurement');
    localStorage.removeItem('patientId');
    localStorage.removeItem('pendingEmbedding');

    navigate('/');
  };

  return (
    <div className="success">
      <div className="success__container">
        <div className="success__content">
          <h2 className="success__message">
            Barcha amallar muvaffaqiyatli bajarildi iltimos chekni oling
          </h2>
          
          <div className="success__icon-wrapper">
            <div className="success__icon-circle">
              <FaCheck className="success__icon" />
            </div>
          </div>
          
          <div className="success__button-wrapper">
            <Button 
              onClick={handleHome} 
              className="success__button"
            >
              BOSH SAHIFA
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
};

export default Success;
