import json
import logging
import os
import re
import urllib.error
import urllib.request
from decimal import Decimal, InvalidOperation

logger = logging.getLogger(__name__)


class GroqValuationError(Exception):
    """Raised for recoverable Groq valuation issues."""


class GroqVehicleValuationService:
    """Service class for AI-based vehicle valuation using Groq Cloud."""

    API_URL = 'https://api.groq.com/openai/v1/chat/completions'

    def __init__(self, api_key=None, model='llama-3.1-8b-instant', timeout=25):
        self.api_key = api_key or os.environ.get('GROQ_API_KEY')
        self.model = model
        self.timeout = timeout

        if not self.api_key:
            raise GroqValuationError('GROQ_API_KEY is not configured.')

    def evaluate_vehicle(self, vehicle_data):
        """Estimate value, fairness, and best market price for a vehicle."""
        logger.debug(f'Starting vehicle valuation for {vehicle_data.get("make")} {vehicle_data.get("model")}')
        
        payload = {
            'model': self.model,
            'temperature': 0.2,
            'response_format': {'type': 'json_object'},
            'messages': [
                {'role': 'system', 'content': self._system_prompt()},
                {'role': 'user', 'content': self._user_prompt(vehicle_data)},
            ],
        }

        body = json.dumps(payload).encode('utf-8')
        request = urllib.request.Request(
            self.API_URL,
            data=body,
            headers={
                'Authorization': f'Bearer {self.api_key}',
                'Content-Type': 'application/json',
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            },
            method='POST',
        )

        logger.debug(f'Sending request to Groq API (timeout={self.timeout}s)')
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw_body = response.read().decode('utf-8')
        except urllib.error.HTTPError as exc:
            response_body = ''
            try:
                response_body = exc.read().decode('utf-8', errors='ignore')
            except:
                pass
            detail = response_body if response_body else str(exc)
            logger.error(f'Groq HTTP error {exc.code}: {detail}')
            raise GroqValuationError(f'Groq API HTTP {exc.code}: {detail}') from exc
        except urllib.error.URLError as exc:
            logger.error(f'Groq URL error: {exc}')
            raise GroqValuationError(f'Groq API request failed: {exc}') from exc
        except Exception as exc:
            logger.exception(f'Unexpected error calling Groq API: {exc}')
            raise GroqValuationError(f'Error calling Groq API: {exc}') from exc
        
        logger.debug(f'Received response from Groq API')

        try:
            parsed = json.loads(raw_body)
            content = parsed['choices'][0]['message']['content']
            model_data = self._parse_json_payload(content)
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            logger.error(f'Failed to parse Groq response: {exc}')
            raise GroqValuationError('Groq API returned an invalid response format.') from exc

        logger.debug('Successfully parsed Groq response')
        normalized = self._normalize_output(model_data)
        normalized['raw_response'] = parsed
        normalized['model_name'] = parsed.get('model', self.model)
        logger.debug(f'Vehicle valuation complete: est_value={normalized["estimated_market_value"]}, fairness={normalized["fairness_assessment"]}')
        return normalized

    def _system_prompt(self):
        return (
            'You are a senior automotive valuation analyst. '
            'You assess fair market value for used cars based on given vehicle attributes. '
            'Always return ONLY a valid JSON object (in JSON format) with exactly these keys: '
            'estimated_market_value, fairness_assessment, suggested_price, explanation. '
            'fairness_assessment must be one of: below_market, fair, above_market. '
            'Use numeric values for prices. '
            'Return valid JSON only, no markdown or extra text.'
        )

    def _user_prompt(self, vehicle_data):
        return (
            'Please estimate market value and pricing fairness for this vehicle and return a JSON response:\n\n'
            f"- Make: {vehicle_data.get('make')}\n"
            f"- Model: {vehicle_data.get('model')}\n"
            f"- Year: {vehicle_data.get('year')}\n"
            f"- Mileage (km): {vehicle_data.get('mileage')}\n"
            f"- Condition: {vehicle_data.get('condition')}\n"
            f"- Transmission: {vehicle_data.get('transmission')}\n"
            f"- Fuel type: {vehicle_data.get('fuel_type')}\n"
            f"- Published price (SEK): {vehicle_data.get('published_price')}\n\n"
            'Return ONLY a valid JSON object with these exact keys: '
            'estimated_market_value (number), fairness_assessment (string: below_market, fair, or above_market), '
            'suggested_price (number), explanation (string). '
            'No markdown, no extra text, just the JSON object.'
        )

    def _parse_json_payload(self, content):
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            match = re.search(r'\{.*\}', content, re.DOTALL)
            if not match:
                raise
            return json.loads(match.group(0))

    def _to_decimal(self, value, field_name):
        try:
            if value is None:
                raise InvalidOperation
            return Decimal(str(value)).quantize(Decimal('0.01'))
        except (InvalidOperation, ValueError, TypeError) as exc:
            raise GroqValuationError(f'Invalid {field_name} returned by Groq API.') from exc

    def _normalize_output(self, data):
        fairness = str(data.get('fairness_assessment', '')).strip().lower().replace('-', '_')
        if fairness not in {'below_market', 'fair', 'above_market'}:
            raise GroqValuationError('Invalid fairness_assessment returned by Groq API.')

        explanation = str(data.get('explanation', '')).strip()
        if not explanation:
            raise GroqValuationError('Missing explanation returned by Groq API.')

        return {
            'estimated_market_value': self._to_decimal(data.get('estimated_market_value'), 'estimated_market_value'),
            'fairness_assessment': fairness,
            'suggested_price': self._to_decimal(data.get('suggested_price'), 'suggested_price'),
            'ai_explanation': explanation,
        }
