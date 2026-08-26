'use client';

import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { useRouter } from 'next/navigation';
import { signupSchema } from '@/features/auth/schemas/signupSchema';
import { useSignup } from '@/features/auth/hooks/useSignup';
import { ROUTES } from '@/core/constants/routes';
import { Button } from '@/shared/components/ui/Button';
import { Input } from '@/shared/components/ui/Input';
import { Label } from '@/shared/components/ui/Label';
import { Select } from '@/shared/components/ui/Select';
import { useToast } from '@/shared/components/toast/ToastProvider';

/**
 * Self-service staff signup — Receptionist, Vitals staff, Doctor, or
 * Inventory Manager (backend/app/modules/auth/signup_schemas.py's
 * SignupRole; every role shares this exact same form/OTP/approval flow,
 * only the `role` field changes which Role gets granted on approval).
 * Field set mirrors PatientIdentityFields/CreateUserRequest's
 * established conventions; `shift` is the one genuinely new field,
 * required for Receptionist/Vitals specifically because the hospital
 * runs exactly two shifts for front-desk and nursing staff — Doctor and
 * Inventory Manager are the two roles that skip it entirely (see
 * signupSchema.js's own comment and backend SignupRequest.
 * _shift_required_unless_shiftless_role: neither has a shift concept
 * anywhere else in this system), so the field is hidden rather than
 * shown with a meaningless choice once either is selected.
 */
export function SignupForm() {
  const router = useRouter();
  const { toast } = useToast();
  const signup = useSignup();
  const {
    register,
    handleSubmit,
    watch,
    formState: { errors, isSubmitting },
  } = useForm({
    resolver: zodResolver(signupSchema),
    defaultValues: {
      fullName: '',
      email: '',
      phoneNumber: '',
      password: '',
      shift: '',
      role: '',
    },
  });

  const role = watch('role');
  // Mirrors backend's `_SHIFTLESS_SIGNUP_ROLES` exactly.
  const isShiftless = role === 'doctor' || role === 'inventory_manager';

  async function onSubmit(values) {
    try {
      // Belt-and-braces alongside the hidden field below: a shift-less
      // signup never carries a shift, regardless of whatever value
      // react-hook-form's uncontrolled input state happens to still
      // hold from before the role was switched. `null`, not `''` — the
      // backend's `shift` field is `Shift | None`, and an empty string
      // is not a valid `Shift` value.
      const payload = isShiftless ? { ...values, shift: null } : values;
      const response = await signup.mutateAsync(payload);
      toast.success({
        title: 'Account created',
        description: "We've sent a verification code to your email.",
      });
      router.push(`${ROUTES.VERIFY_EMAIL}?email=${encodeURIComponent(response.data.email)}`);
    } catch (error) {
      toast.error({
        title: 'Unable to create your account',
        description: error.message,
        onRetry: () => onSubmit(values),
      });
    }
  }

  return (
    <form onSubmit={handleSubmit(onSubmit)} className="flex w-full max-w-sm flex-col gap-4">
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="fullName">Full Name</Label>
        <Input id="fullName" autoFocus autoComplete="name" {...register('fullName')} />
        {errors.fullName ? (
          <p className="text-xs text-destructive">{errors.fullName.message}</p>
        ) : null}
      </div>

      <div className="flex flex-col gap-1.5">
        <Label htmlFor="email">Email</Label>
        <Input
          id="email"
          type="email"
          autoComplete="email"
          placeholder="you@gmail.com"
          {...register('email')}
        />
        {errors.email ? <p className="text-xs text-destructive">{errors.email.message}</p> : null}
      </div>

      <div className="flex flex-col gap-1.5">
        <Label htmlFor="phoneNumber">Phone Number</Label>
        <Input id="phoneNumber" autoComplete="tel" {...register('phoneNumber')} />
        {errors.phoneNumber ? (
          <p className="text-xs text-destructive">{errors.phoneNumber.message}</p>
        ) : null}
      </div>

      <div className="flex flex-col gap-1.5">
        <Label htmlFor="role">I am signing up as</Label>
        <Select id="role" defaultValue="" {...register('role')}>
          <option value="" disabled>
            Select your role
          </option>
          <option value="receptionist">Receptionist</option>
          <option value="vitals">Vitals Staff (Nurse)</option>
          <option value="doctor">Doctor</option>
          <option value="inventory_manager">Inventory Manager</option>
        </Select>
        {errors.role ? <p className="text-xs text-destructive">{errors.role.message}</p> : null}
      </div>

      {isShiftless ? null : (
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="shift">Shift</Label>
          <Select id="shift" defaultValue="" {...register('shift')}>
            <option value="" disabled>
              Select your shift
            </option>
            <option value="morning">Morning</option>
            <option value="night">Night</option>
          </Select>
          {errors.shift ? (
            <p className="text-xs text-destructive">{errors.shift.message}</p>
          ) : null}
        </div>
      )}

      <div className="flex flex-col gap-1.5">
        <Label htmlFor="password">Password</Label>
        <Input
          id="password"
          type="password"
          autoComplete="new-password"
          placeholder="At least 12 characters"
          {...register('password')}
        />
        {errors.password ? (
          <p className="text-xs text-destructive">{errors.password.message}</p>
        ) : null}
      </div>

      <Button type="submit" disabled={isSubmitting} className="w-full">
        {isSubmitting ? 'Creating account…' : 'Create Account'}
      </Button>
    </form>
  );
}
