import React, { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import Button from '../components/Button';
import '../styles/pages/_blood-pressure-measurement.scss';

const BloodPressureMeasurement = () => {
  const navigate = useNavigate();
  
  // Состояния для данных
  const [systolic, setSystolic] = useState('');
  const [diastolic, setDiastolic] = useState('');
  const [pulse, setPulse] = useState('');
  
  // Состояния интерфейса
  const [showKiydim, setShowKiydim] = useState(false);
  const [cuffWorn, setCuffWorn] = useState(false);
  const [isMeasuring, setIsMeasuring] = useState(false);

  const pollingRef = useRef(null);
  const API_BASE_URL = 'http://localhost:8000'; // Убедитесь, что адрес совпадает с вашим FastAPI

  useEffect(() => {
    // Показать кнопку через 3 секунды
    const timer = setTimeout(() => {
      setShowKiydim(true);
    }, 3000);

    return () => {
      clearTimeout(timer);
      stopPolling();
    };
  }, []);

  const stopPolling = () => {
    if (pollingRef.current) {
      clearInterval(pollingRef.current);
      pollingRef.current = null;
    }
  };

  const startPollingData = () => {
    setIsMeasuring(true);
    pollingRef.current = setInterval(async () => {
      try {
        const response = await fetch(`${API_BASE_URL}/blood-pressure`);
        const data = await response.json();
        
        // Если данные не "0", значит измерение завершено
        if (data.systolic !== "0" && data.systolic !== 0) {
          setSystolic(data.systolic);
          setDiastolic(data.diastolic);
          setPulse(data.pulse);
          setIsMeasuring(false);
          stopPolling();
        }
      } catch (error) {
        console.error("Ma'lumot olishda xatolik:", error);
      }
    }, 2000); // Опрос каждые 2 секунды
  };

  const handleKiydim = async () => {
    setCuffWorn(true);
    try {
      // 1. Посылаем сигнал аппарату начать надув
      await fetch(`${API_BASE_URL}/start-bp`);
      // 2. Начинаем опрашивать результат
      startPollingData();
    } catch (error) {
      console.error("Apparatni ishga tushirib bo'lmadi");
      alert("Apparat bilan aloqa yo'q!");
    }
  };

  const handleNext = () => {
    localStorage.setItem('bloodPressureSystolic', systolic);
    localStorage.setItem('bloodPressureDiastolic', diastolic);
    localStorage.setItem('pulse', pulse);
    
    const isAllMeasurementsMode = localStorage.getItem('isAllMeasurementsMode') === 'true';
    
    if (isAllMeasurementsMode) {
      const measurementQueue = JSON.parse(localStorage.getItem('measurementQueue') || '[]');
      const currentIndex = parseInt(localStorage.getItem('currentMeasurementIndex') || '0');
      const nextIndex = currentIndex + 1;
      
      if (nextIndex < measurementQueue.length) {
        localStorage.setItem('currentMeasurementIndex', nextIndex.toString());
        navigate(`/measurement/${measurementQueue[nextIndex]}`);
      } else {
        localStorage.removeItem('measurementQueue');
        localStorage.removeItem('currentMeasurementIndex');
        localStorage.removeItem('isAllMeasurementsMode');
        navigate('/success');
      }
    } else {
      navigate('/success');
    }
  };

  // Кнопка "Keyingi" активна только когда есть реальные данные
  const hasAllValues = systolic !== '' && parseInt(systolic) > 0;

  return (
    <div className="blood-pressure-measurement">
      <div className="blood-pressure-measurement__container">
        <div className="blood-pressure-measurement__content">
          <div className="blood-pressure-measurement__instructions">
            <p className="blood-pressure-measurement__text">
              {isMeasuring 
                ? "O'lchash jarayoni ketmoqda, iltimos qimirlamay turing..." 
                : "Iltimos qon bosimi va puls miqdorini o'lchash uchun bosm qopchasini qo'lingizga kiying"}
            </p>
          </div>

          <div className="blood-pressure-measurement__display">
            <div className={`blood-pressure-measurement__display-box ${isMeasuring ? 'measuring' : ''}`}>
              <div className="blood-pressure-measurement__display-section">
                <h3 className="blood-pressure-measurement__display-title">Qon bosimi</h3>
                <div className="blood-pressure-measurement__display-content">
                  <img 
                    src="/assets/icons/bloodPressure_b.svg" 
                    alt="Blood pressure icon" 
                    className="blood-pressure-measurement__display-icon"
                  />
                  <input
                    type="text"
                    className="blood-pressure-measurement__display-value"
                    value={systolic || (isMeasuring ? "..." : "--")}
                    readOnly
                    placeholder="--"
                  />
                  <span className="blood-pressure-measurement__display-separator">/</span>
                  <input
                    type="text"
                    className="blood-pressure-measurement__display-value"
                    value={diastolic || (isMeasuring ? "..." : "--")}
                    readOnly
                    placeholder="--"
                  />
                </div>
                <span className="blood-pressure-measurement__display-unit">mmHg</span>
              </div>
              
              <div className="blood-pressure-measurement__display-section">
                <h3 className="blood-pressure-measurement__display-title">Puls miqdori</h3>
                <div className="blood-pressure-measurement__display-content">
                  <img 
                    src="/assets/icons/bloodOxygen_b.svg" 
                    alt="Pulse icon" 
                    className="blood-pressure-measurement__display-icon"
                  />
                  <input
                    type="text"
                    className="blood-pressure-measurement__display-value"
                    value={pulse || (isMeasuring ? "..." : "--")}
                    readOnly
                    placeholder="--"
                  />
                  <span className="blood-pressure-measurement__display-unit">bpm</span>
                </div>
              </div>
            </div>
          </div>

          <div className="blood-pressure-measurement__illustration">
            <img 
              src="/assets/imgs/pressure.webp" 
              alt="Instructions for cuff placement" 
              className="blood-pressure-measurement__image"
            />
          </div>

          <div className="blood-pressure-measurement__buttons">
            {showKiydim && !cuffWorn && (
              <Button 
                onClick={handleKiydim} 
                className="blood-pressure-measurement__button blood-pressure-measurement__button--kiydim"
              >
                Kiydim
              </Button>
            )}
            
            {hasAllValues && !isMeasuring && (
              <Button 
                onClick={handleNext} 
                className="blood-pressure-measurement__button blood-pressure-measurement__button--next"
              >
                Keyingi
              </Button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};

export default BloodPressureMeasurement;