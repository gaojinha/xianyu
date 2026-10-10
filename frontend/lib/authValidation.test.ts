import { describe, it, expect } from 'vitest';
import { validateUsername, validateEmail, validatePassword } from './authValidation';

describe('validateUsername', () => {
  it('拒绝空', () => {
    expect(validateUsername('')[0]).toBe(false);
  });
  it('拒绝过短', () => {
    expect(validateUsername('ab')[0]).toBe(false);
  });
  it('拒绝非法字符', () => {
    expect(validateUsername('a b!')[0]).toBe(false);
  });
  it('接受合法用户名', () => {
    expect(validateUsername('gao_123')[0]).toBe(true);
  });
});

describe('validateEmail', () => {
  it('拒绝空与格式错误', () => {
    expect(validateEmail('')[0]).toBe(false);
    expect(validateEmail('abc')[0]).toBe(false);
  });
  it('接受合法邮箱', () => {
    expect(validateEmail('gaojinha@163.com')[0]).toBe(true);
  });
});

describe('validatePassword', () => {
  it('拒绝空、过短、纯字母、纯数字', () => {
    expect(validatePassword('')[0]).toBe(false);
    expect(validatePassword('ab1')[0]).toBe(false);
    expect(validatePassword('abcdefgh')[0]).toBe(false);
    expect(validatePassword('12345678')[0]).toBe(false);
  });
  it('接受字母+数字且长度达标', () => {
    expect(validatePassword('abc12345')[0]).toBe(true);
  });
});
