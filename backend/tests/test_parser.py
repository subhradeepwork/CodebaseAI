from app.services.parser import parse_source


def test_lambda_mjs_detection():
    src = '''
import { DynamoDBClient, PutItemCommand } from "@aws-sdk/client-dynamodb";
const db = new DynamoDBClient({});
export const handler = async (event) => {
  const table = process.env.CUSTOMER_TABLE;
  return new PutItemCommand({ TableName: table });
};
'''
    result = parse_source("lambdaBackend/createCustomer/index.mjs", src)
    assert result.language == "javascript"
    assert result.metadata["is_lambda_handler"] is True
    assert "CUSTOMER_TABLE" in result.metadata["environment_variables"]
    assert "@aws-sdk/client-dynamodb" in result.metadata["aws_sdk_packages"]
    assert any(s.name == "handler" and s.kind == "aws_lambda_handler" for s in result.symbols)


def test_react_and_hook_detection():
    src = '''
export const CustomerPage = () => { return <div>Hello</div>; };
export const useCustomer = () => fetch('/api/customer');
'''
    result = parse_source("src/CustomerPage.tsx", src)
    kinds = {s.name: s.kind for s in result.symbols}
    assert kinds.get("CustomerPage") == "react_component"
    assert kinds.get("useCustomer") == "react_hook"


def test_karate_calls():
    src = '''
@smoke
Feature: Login
Scenario: Valid login
  * def util = Java.type('com.acme.AuthHelper')
  * call read('classpath:common/auth.feature')
'''
    result = parse_source("tests/login.feature", src)
    assert any(s.name == "Valid login" for s in result.symbols)
    assert "classpath:common/auth.feature" in result.metadata["feature_calls"]
    assert "com.acme.AuthHelper" in result.metadata["java_types"]

def test_playwright_detection():
    src = '''
import { test, expect } from '@playwright/test';

test.describe('checkout', () => {
  test('creates an order', async ({ page }) => {
    await page.goto('/checkout');
    await page.getByRole('button', { name: 'Pay' }).click();
  });
});
'''
    result = parse_source('e2e/checkout.spec.ts', src)
    assert result.metadata['is_playwright'] is True
    assert 'creates an order' in result.metadata['playwright_tests']
    assert any(s.kind == 'playwright_test' and s.name == 'creates an order' for s in result.symbols)
