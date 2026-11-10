export function examAvailability(exam, now = Date.now()) {
  if (exam.closesAt != null && now >= exam.closesAt) return 'expired';
  if (exam.acceptingAttempts === false) return 'closed';
  if (exam.opensAt != null && now < exam.opensAt) return 'scheduled';
  return 'open';
}
export const availabilityLabels = {
  expired: 'ปิดสอบแล้วตามกำหนดเวลา',
  closed: 'อาจารย์ปิดสอบแล้ว',
  scheduled: 'ยังไม่ถึงเวลาเปิดสอบ',
  open: 'เปิดสอบอยู่',
};
