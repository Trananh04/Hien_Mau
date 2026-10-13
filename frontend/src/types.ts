export interface NewsItem {
  id: number;
  date: string;
  title: string;
  excerpt: string;
  image: string;
  category: 'su-kien' | 'khan-cap' | 'chia-se';
  fullContent?: string;
}

export interface VolunteerRegistrationData {
  fullName: string;
  birthYear: string;
  address: string;
  gender: 'Nam' | 'Nữ' | 'Khác';
  phone: string;
  zalo: string;
  bloodType: string;
  rhFactor: 'Rh+' | 'Rh-' | 'Chưa rõ';
  donationStatus: string;
  canDonatePlatelets: 'Có' | 'Không' | 'Chưa rõ';
  selectedAreas: string[];
}

export interface PatientBloodRequestData {
  patientName: string;
  birthYear: string;
  requestPlatelets: boolean;
  bloodType: string;
  unitsNeeded: string;
  patientCondition: string;
  hospitalName: string;
  hospitalDistrict: string;
  additionalNotes: string;
  contactName: string;
  contactPhone: string;
  relationship: string;
}
