import React, { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import Button from '../components/Button';
import '../styles/pages/_weight-height-measurement.scss';

const WeightHeightMeasurement = () => {
  const navigate = useNavigate();
  const [weight, setweight] = useState('');
  const [height, setheight] = useState('');

  const prevWeight = useRef(0);
  const prevHeight = useRef(0);

  const stopSensors = async () => {
    try {
      await fetch('http://127.0.0.1:8000/stop-sensors');
    } catch (err) {
      console.error('Stop Sensors Error:', err);
    }
  };

  const handleFinish = async () => {
    // 1. Останавливаем датчики на бэкенде
    await stopSensors();

    // 2. Сохраняем данные
    localStorage.setItem('weight', weight);
    localStorage.setItem('height', height);
    
    const isAllMeasurementsMode = localStorage.getItem('isAllMeasurementsMode') === 'true';
    
    if (isAllMeasurementsMode) {
      const measurementQueue = JSON.parse(localStorage.getItem('measurementQueue') || '[]');
      const currentIndex = parseInt(localStorage.getItem('currentMeasurementIndex') || '0');
      const nextIndex = currentIndex + 1;
      
      if (nextIndex < measurementQueue.length) {
        localStorage.setItem('currentMeasurementIndex', nextIndex.toString());
        const nextMeasurement = measurementQueue[nextIndex];
        navigate(`/measurement/${nextMeasurement}`);
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

  const hasBothValues = weight !== '' && parseFloat(weight) > 0 && height !== '' && parseFloat(height) > 0;

  useEffect(() => {
    // Включаем датчики при входе на страницу
    const startSensors = async () => {
        try {
            await fetch('http://127.0.0.1:8000/start-sensors');
        } catch (e) { console.error(e); }
    };
    startSensors();

    const fetchData = async () => {
      try {
        const weightRes = await fetch('http://127.0.0.1:8000/weight');
        const weightData = await weightRes.json();
        const newWeight = parseFloat(weightData.weight);

        if (Math.abs(prevWeight.current - newWeight) > 0.15 || prevWeight.current === 0) {
          setweight(newWeight.toFixed(2));
          prevWeight.current = newWeight;
        }

        const heightRes = await fetch('http://127.0.0.1:8000/height');
        const heightData = await heightRes.json();
        
        if (heightData.height !== "error") {
          const newHeight = parseFloat(heightData.height);
          if (Math.abs(prevHeight.current - newHeight) > 0.4 || prevHeight.current === 0) {
            setheight(newHeight.toFixed(1));
            prevHeight.current = newHeight;
          }
        }
      } catch (err) {
        console.error('API Error:', err);
      }
    };

    const intervalId = setInterval(fetchData, 1000);

    return () => {
        clearInterval(intervalId);
    };
  }, []);

  return (
    <div className="weight-height-measurement">
      <div className="weight-height-measurement__container">
        <div className="weight-height-measurement__content">
          <div className="weight-height-measurement__instructions">
            <p className="weight-height-measurement__text">Og'irlik hamda boʻy oʻlchanmoqda.</p>
            <p className="weight-height-measurement__text">Iltimos qaddingizni rostlagan holda to'g'riga qarab turing</p>
          </div>

          <div className="weight-height-measurement__display">
            <div className="weight-height-measurement__display-box">
              <h3 className="weight-height-measurement__display-title">Og'irlik va bo'y</h3>
              <div className="weight-height-measurement__display-content">
                <div className="weight-height-measurement__display-row">
                  <img src="/assets/icons/weight_b.svg" alt="Weight" className="weight-height-measurement__display-icon" />
                  <input type="text" className="weight-height-measurement__display-value" value={weight} readOnly placeholder="--" />
                  <span className="weight-height-measurement__display-unit">kg</span>
                </div>
                <div className="weight-height-measurement__display-row">
                  <img src="/assets/icons/height_b.svg" alt="Height" className="weight-height-measurement__display-icon" />
                  <input type="text" className="weight-height-measurement__display-value" value={height} readOnly placeholder="--" />
                  <span className="weight-height-measurement__display-unit">sm</span>
                </div>
              </div>
            </div>
          </div>

          <div className="weight-height-measurement__illustration">
            <img src="/assets/imgs/height.webp" alt="Measurement" className="weight-height-measurement__image" />
          </div>

          {hasBothValues && (
            <div className="weight-height-measurement__button-wrapper">
              <Button onClick={handleFinish} className="weight-height-measurement__button">Tugatish</Button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default WeightHeightMeasurement;