import { z } from 'zod';

const optionalNumber = (min, max) =>
  z
    .union([z.string(), z.number()])
    .optional()
    .transform((value) => (value === '' || value === undefined ? undefined : Number(value)))
    .refine((value) => value === undefined || (value >= min && value <= max), {
      message: `Must be between ${min} and ${max}`,
    });

export const recordVitalsSchema = z.object({
  systolic_bp: optionalNumber(0, 300),
  diastolic_bp: optionalNumber(0, 300),
  pulse_rate: optionalNumber(0, 300),
  temperature_celsius: optionalNumber(20, 45),
  weight_kg: optionalNumber(0, 500),
  height_cm: optionalNumber(0, 300),
  spo2_percent: optionalNumber(0, 100),
  notes: z.string().max(2000).optional().or(z.literal('')),
});
