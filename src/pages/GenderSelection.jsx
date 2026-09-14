import React from 'react';
import { useNavigate } from 'react-router-dom';
import Button from '../components/Button';
import '../styles/pages/_gender-selection.scss';

const GenderSelection = () => {
  const navigate = useNavigate();

  const handleGenderSelect = (gender) => {
    // Store gender selection
    localStorage.setItem('gender', gender);
    
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
        fetch()
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
